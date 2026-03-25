from __future__ import annotations

from pathlib import Path
import re

from chatbot.src.onboarding_v2.models.compile import BackendWiringBundle, EditOperation, SupportingArtifactBundle
from chatbot.src.onboarding_v2.models.planning import HostBackendPlan


def compile_django_backend_bundle(
    *,
    source_root: str | Path,
    plan: HostBackendPlan,
) -> BackendWiringBundle:
    root = Path(source_root)
    route_path = root / plan.route_target
    if not route_path.exists():
        raise ValueError(f"django route target not found: {plan.route_target}")
    route_original = route_path.read_text(encoding="utf-8")
    route_updated = _ensure_django_route_wiring(route_original)
    target_paths = [plan.route_target]
    operations = [
        EditOperation(
            path=plan.route_target,
            operation="replace_text",
            old=route_original,
            new=route_updated,
        )
    ]

    if plan.order_action_target:
        order_action_path = root / plan.order_action_target
        if not order_action_path.exists():
            raise ValueError(f"django order action target not found: {plan.order_action_target}")
        order_action_original = order_action_path.read_text(encoding="utf-8")
        order_action_updated = _augment_django_order_action_endpoint(
            order_action_original,
            plan=plan,
        )
        target_paths.append(plan.order_action_target)
        operations.append(
            EditOperation(
                path=plan.order_action_target,
                operation="replace_text",
                old=order_action_original,
                new=order_action_updated,
            )
        )
    supporting_files = []
    if plan.generated_handler_path:
        supporting_files.append(
            SupportingArtifactBundle(
                bundle_id="supporting:chat-auth-module",
                path=plan.generated_handler_path,
                reason="generated django chat auth bridge",
                content=_build_django_chat_auth_module(
                    auth_source=plan.auth_handler_source,
                    site_id=plan.site_id,
                ),
            )
        )
    return BackendWiringBundle(
        bundle_id="backend:django-wiring",
        strategy=plan.strategy,
        target_paths=target_paths,
        operations=operations,
        supporting_files=supporting_files,
        handler_reference="chat_auth.chat_auth_token",
    )


def _ensure_django_route_wiring(content: str) -> str:
    lines = content.splitlines(keepends=True)
    import_line = "from chat_auth import chat_auth_token\n"
    route_line = '    path("api/chat/auth-token", chat_auth_token),\n'
    if import_line not in lines:
        insert_index = 0
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("from ") or stripped.startswith("import "):
                insert_index = index + 1
                continue
            if stripped == "":
                if insert_index:
                    insert_index = index + 1
                continue
            break
        lines[insert_index:insert_index] = [import_line]
    if route_line not in lines:
        urlpatterns_index = next((index for index, line in enumerate(lines) if "urlpatterns" in line), None)
        if urlpatterns_index is None:
            if lines and lines[-1].strip():
                lines.append("\n")
            lines.extend(["urlpatterns = [\n", route_line, "]\n"])
        else:
            closing_index = _find_list_closing_index(lines, start_index=urlpatterns_index)
            if closing_index is None:
                lines.append(route_line)
            else:
                lines.insert(closing_index, route_line)
    return "".join(lines)


def _find_list_closing_index(lines: list[str], *, start_index: int) -> int | None:
    depth = 0
    seen_open = False
    for index in range(start_index, len(lines)):
        line = lines[index]
        if "[" in line:
            depth += line.count("[")
            seen_open = True
        if "]" in line:
            depth -= line.count("]")
            if seen_open and depth <= 0:
                return index
    return None


def _build_django_chat_auth_module(*, auth_source: str, site_id: str) -> str:
    source_module = auth_source.removesuffix(".py").replace("/", ".")
    if source_module.startswith("backend."):
        source_module = source_module.removeprefix("backend.")
    return (
        "from __future__ import annotations\n\n"
        "from django.http import JsonResponse\n"
        "from django.views.decorators.csrf import csrf_exempt\n\n"
        f"from {source_module} import _build_user_payload, _find_active_session\n\n\n"
        "@csrf_exempt\n"
        "def chat_auth_token(request):\n"
        '    """Generated onboarding bridge endpoint."""\n'
        "    session = _find_active_session(request)\n"
        "    if not session:\n"
        "        return JsonResponse(\n"
        "            {\n"
        '                "authenticated": False,\n'
        f'                "site_id": "{site_id}",\n'
        '                "access_token": "",\n'
        '                "user": None,\n'
        '            },\n'
        "            status=200,\n"
        "        )\n"
        "    access_token = str(session.token)\n"
        "    return JsonResponse(\n"
        "        {\n"
        '            "authenticated": True,\n'
        f'            "site_id": "{site_id}",\n'
        '            "access_token": access_token,\n'
        '            "user": _build_user_payload(session.user),\n'
        "        },\n"
        "        status=200,\n"
        "    )\n"
    )


def _augment_django_order_action_endpoint(content: str, *, plan: HostBackendPlan) -> str:
    if plan.exchange_strategy != "augment_existing_order_action_endpoint":
        return content
    updated = _ensure_product_import(content)
    updated = _ensure_exchange_helper(
        updated,
        option_field=plan.order_action_new_option_field,
    )
    return _replace_exchange_handler(
        updated,
        serializer_name=plan.order_action_response_serializer,
        exchange_status_transition=plan.exchange_status_transition,
    )


def _ensure_product_import(content: str) -> str:
    import_line = "from products.models import Product\n"
    if import_line in content:
        return content
    insertion_index = _find_local_order_models_import_end(content)
    if insertion_index is None:
        raise ValueError("django order action target missing order model import anchor")
    return content[:insertion_index] + import_line + content[insertion_index:]


def _ensure_exchange_helper(content: str, *, option_field: str) -> str:
    helper = (
        "def _resolve_exchange_product(request):\n"
        f'    new_option_id = request.data.get("{option_field}")\n'
        "    if new_option_id in (None, \"\"):\n"
        "        return None\n"
        "    selected_product = get_object_or_404(Product, pk=new_option_id)\n"
        "    return selected_product\n"
    )
    if "def _resolve_exchange_product(request):\n" in content:
        return content
    anchor = "def _handle_exchange(order, request):\n"
    if anchor not in content:
        raise ValueError("django order action target missing exchange handler")
    return content.replace(anchor, helper + "\n" + anchor, 1)


def _replace_exchange_handler(
    content: str,
    *,
    serializer_name: str,
    exchange_status_transition: str,
) -> str:
    start_marker = "def _handle_exchange(order, request):\n"
    start_index = content.find(start_marker)
    if start_index < 0:
        raise ValueError("django order action target missing exchange handler")
    end_index = _find_next_top_level_def_index(content, start_index=start_index + len(start_marker))
    if end_index is None:
        end_index = len(content)
    current = content[start_index:end_index]
    replacement = (
        "def _handle_exchange(order, request):\n"
        "    if order.payment_status != Order.PaymentStatus.PAID:\n"
        "        return add_cors_headers(\n"
        "            Response(\n"
        '                {"detail": "결제된 주문만 교환을 요청할 수 있습니다."},\n'
        "                status=status.HTTP_400_BAD_REQUEST,\n"
        "            )\n"
        "        )\n"
        "    if order.status == Order.Status.EXCHANGE_REQUESTED:\n"
        "        return add_cors_headers(\n"
        "            Response(\n"
        '                {"detail": "이미 교환 접수된 주문입니다."},\n'
        "                status=status.HTTP_400_BAD_REQUEST,\n"
        "            )\n"
        "        )\n"
        "    if order.status in (Order.Status.CANCELLED, Order.Status.REFUNDED):\n"
        "        return add_cors_headers(\n"
        "            Response(\n"
        '                {"detail": "취소되었거나 환불된 주문은 교환할 수 없습니다."},\n'
        "                status=status.HTTP_400_BAD_REQUEST,\n"
        "            )\n"
        "        )\n"
        "    if order.status not in (Order.Status.SHIPPING, Order.Status.DELIVERED):\n"
        "        return add_cors_headers(\n"
        "            Response(\n"
        '                {"detail": "배송 중이거나 배송 완료된 주문만 교환 접수가 가능합니다."},\n'
        "                status=status.HTTP_400_BAD_REQUEST,\n"
        "            )\n"
        "        )\n"
        "\n"
        "    selected_product = _resolve_exchange_product(request)\n"
        "    if selected_product is not None:\n"
        "        order.product = selected_product\n"
        "        order.total_price = selected_product.price * order.quantity\n"
        "        update_fields = [\"product\", \"total_price\", \"status\"]\n"
        "    else:\n"
        "        update_fields = [\"status\"]\n"
        "\n"
        f"    order.status = Order.Status.{exchange_status_transition}\n"
        "    order.save(update_fields=update_fields)\n"
        "\n"
        "    return add_cors_headers(\n"
        "        Response(\n"
        "            {\n"
        '                "message": "교환이 접수되었습니다.",\n'
        f'                "order": {serializer_name}(order, request),\n'
        "            }\n"
        "        )\n"
        "    )\n"
    )
    return content.replace(current, replacement, 1)


def _find_local_order_models_import_end(content: str) -> int | None:
    lines = content.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.lstrip().startswith("from .models import"):
            index += 1
            continue
        block_end = index + 1
        if "(" in line and ")" not in line:
            balance = line.count("(") - line.count(")")
            while block_end < len(lines) and balance > 0:
                balance += lines[block_end].count("(") - lines[block_end].count(")")
                block_end += 1
        import_block = "".join(lines[index:block_end])
        if re.search(r"\bOrder\b", import_block):
            return sum(len(current_line) for current_line in lines[:block_end])
        index = block_end
    return None


def _find_next_top_level_def_index(content: str, *, start_index: int) -> int | None:
    match = re.search(r"^def\s+\w+\(", content[start_index:], flags=re.MULTILINE)
    if match is None:
        return None
    return start_index + match.start()
