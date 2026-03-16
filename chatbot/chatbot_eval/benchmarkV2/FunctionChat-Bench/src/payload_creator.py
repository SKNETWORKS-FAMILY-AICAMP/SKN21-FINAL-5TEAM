import os
import json
from functools import wraps
from typing import Any, Callable
from tqdm import tqdm
import src.utils as utils
from src.formatter import (
    CommonRequestFormatter,
    DialogRequestFormatter,
    SingleCallRequestFormatter,
)

import sys
data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
if data_dir not in sys.path:
    sys.path.append(data_dir)




def validate_params(kwargs):
    expected_types = {
        'request_file_path': str,
        'input_file_path': str,
        'system_prompt_file_path': str,
        'reset': bool,
        'tools_type': str
    }
    tools_type_list = ['all', '4_close', '4_random', '8_close', '8_random', 'exact']
    for key, expected_type in expected_types.items():
        if key == 'tools_type' and 'tools_type' in kwargs:
            if kwargs[key] is None:
                pass
            elif not isinstance(kwargs[key], expected_type):
                raise ValueError(f"Expected type for {key} is {expected_type}, but got {type(kwargs[key])}.")
            elif kwargs[key] not in tools_type_list:
                raise ValueError(f"tools_type must be one of {tools_type_list}.")
        elif key in kwargs and not isinstance(kwargs[key], expected_type):
            raise ValueError(f"Expected type for {key} is {expected_type}, but got {type(kwargs[key])}.")


def type_check(validate: Callable[[Any, Any], None]):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            validate(kwargs)
            return func(*args, **kwargs)
        return wrapper
    return decorator


class AbstractPayloadCreator:
    """
    An abstract class designed to create payloads for API requests based on provided parameters and system prompts.
    """
    def __init__(self, temperature, max_size, system_prompt_file_path):
        """
        Initializes the payload creator with temperature settings, maximum payload list size, and a path to a system prompt file.

        Parameters:
            temperature (float): Determines the variability of the model's responses.
            max_size (int): Maximum size or number of payloads to maintain.
            system_prompt_file_path (str): Path to a file containing the prompt text used in payloads.
        """
        self.temperature = temperature
        self.max_size = max_size
        self.system_prompt = None
        if system_prompt_file_path:
            self.system_prompt = self.get_prompt_text(system_prompt_file_path)

    def create_payload(self, **kwargs):
        """
        Abstract method to create a payload for an API request. Must be implemented by subclasses.

        Raises:
            NotImplementedError: Indicates that the method needs to be implemented by the subclass.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def get_prompt_text(self, file_path):
        """
        Retrieves and returns the prompt text from a specified file.

        Parameters:
            file_path (str): The path to the file containing the prompt text.

        Returns:
            str: The prompt text, stripped of any leading/trailing whitespace.
        """
        prompt = ''
        if file_path and os.path.isfile(file_path):
            with open(file_path, 'r', encoding="utf-8") as ff:
                prompt = ff.read().strip()
        return prompt

    def load_cached_payload(self, request_file_path):
        """
        Loads cached payload list from a specified file if it exists and meets the required size.

        Parameters:
            request_file_path (str): Path to the file containing cached payloads.

        Returns:
            list: A list of cached payloads if they exist; otherwise, an empty list.
        """
        if utils.is_exist_file(request_file_path):
            api_request_list = utils.load_to_jsonl(request_file_path)
            if len(api_request_list) == self.max_size:
                print(f"[[already existed request jsonl file]] ..{len(api_request_list)}\npath : {request_file_path}")
                print(f"[[already existed request jsonl file]] ..{len(api_request_list)}")
                return api_request_list
            print("[[recreate requests jsonl list]]")
        else:
            print("[[create requests jsonl list]]")
        return []


class CommonPayloadCreator(AbstractPayloadCreator):
    def __init__(self, temperature):
        super().__init__(temperature, 0, None)

    @type_check(validate_params)
    def create_payload(self, **kwargs):
        test_set = utils.load_to_jsonl(kwargs['input_file_path'])
        self.max_size = len(test_set)
        api_request_list = []
        if kwargs['reset'] is False:
            api_request_list = self.load_cached_payload(kwargs['request_file_path'])
            if len(api_request_list) == self.max_size:
                return api_request_list
        else:
            print("[[reset!! create requests jsonl file]]")
        # 2. create requests json list
        for idx, test_input in enumerate(tqdm(test_set)):
            # test_input keys = ['serial_num', 'category', 'input_message', 'input_tools', 'type_of_output', 'ground_truth', 'acceptable_arguments']
            serial_num = test_input['serial_num']
            category = test_input['category']
            tools = test_input['input_tools']
            ground_truth = test_input['ground_truth']
            acceptable_arguments = test_input['acceptable_arguments']
            type_of_output = test_input['type_of_output']
            arguments = {}
            arguments['serial_num'] = serial_num
            arguments['category'] = category
            arguments['tools'] = tools
            arguments['ground_truth'] = ground_truth
            arguments['type_of_output'] = type_of_output
            arguments['acceptable_arguments'] = acceptable_arguments
            arguments['messages'] = test_input['input_messages']
            arguments['temperature'] = self.temperature
            arguments['tool_choice'] = 'auto'
            api_request_list.append(CommonRequestFormatter(**arguments).to_dict())
        # 3. write requests jsonl file
        with open(kwargs['request_file_path'], 'w', encoding='utf-8-sig') as fi:
            for api_request in api_request_list:
                fi.write(f"{json.dumps(api_request, ensure_ascii=False)}\n")
        return api_request_list


class DialogPayloadCreator(AbstractPayloadCreator):
    def __init__(self, temperature, system_prompt_file_path):
        super().__init__(temperature, 200, system_prompt_file_path)
        
        # Scenario to prompt file mapping (shared with evaluation_handler)
        self.scenario_file_map = {
            "cancel": "1_cancel_order_system_prompt.txt",
            "refund": "2_refund_request_system_prompt.txt",
            "exchange": "3_exchange_request_system_prompt.txt",
            "shipping": "5_order_detail_lookup_system_prompt.txt",
            "get_user_orders": "4_order_list_lookup_system_prompt.txt"
        }
        from src.paths import BENCH_ROOT
        self.prompts_dir = os.path.join(str(BENCH_ROOT), 'data', 'system_prompts')

    def _get_branch_prompt(self, scenario_name, scenario_id, user_id, user_email):
        """Loads a scenario-specific prompt if available, falling back to global system_prompt."""
        target_scenario = scenario_name
        if not target_scenario and scenario_id:
            try:
                s_id = int(str(scenario_id).split('-')[0])
                SCENARIO_MAP_LOCAL = {
                    1: "cancel", 2: "refund", 3: "exchange",
                    4: "get_user_orders", 5: "shipping"
                }
                target_scenario = SCENARIO_MAP_LOCAL.get(s_id)
            except:
                pass
        
        prompt_file = self.scenario_file_map.get(target_scenario)
        if prompt_file:
            path = os.path.join(self.prompts_dir, prompt_file)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        base_prompt = content.replace("{user_id}", str(user_id)).replace("{user_email}", str(user_email))
                        return base_prompt
                except Exception as e:
                    print(f"[WARN] Failed to load branch prompt {path}: {e}")
        
        # Fallback
        return self.system_prompt

    @type_check(validate_params)
    def create_payload(self, **kwargs):
        test_set = utils.load_to_jsonl(kwargs['input_file_path'])
        # update input file max_size
        self.max_size = len(test_set)

        # Load full tools for restoration if needed
        full_tools_path = os.path.join(os.path.dirname(kwargs['input_file_path']), 'tools.json')
        full_tools_lookup = {}
        if os.path.exists(full_tools_path):
            try:
                with open(full_tools_path, 'r', encoding='utf-8') as f:
                    all_tools = json.load(f)
                    for t in all_tools:
                        full_tools_lookup[t['function']['name']] = t
            except Exception as e:
                print(f"[WARN] Failed to load tools.json for restoration: {e}")

        # kwargs keys = ['input_file_path', 'request_file_path', 'reset']
        # 1. check to cached file
        api_request_list = []
        if kwargs['reset'] is False:
            api_request_list = self.load_cached_payload(kwargs['request_file_path'])
            if len(api_request_list) == self.max_size:
                return api_request_list
        else:
            print("[[reset!! create requests jsonl file]]")
            # 2. create requests json list
            for idx, test_input in enumerate(tqdm(test_set)):
                # Handle new format (Flattened & New Schema)
                is_flattened = ('relevant_tools' in test_input) or ('tools' in test_input and 'turns' not in test_input)
                has_messages = ('dialogue' in test_input or 'messages' in test_input)
                
                if is_flattened and has_messages:
                    # Restore full tools if possible
                    tools = []
                    relevant_tools_list = test_input.get('relevant_tools') or test_input.get('tools', [])
                    for rt in relevant_tools_list:
                        if 'function' in rt:
                            name = rt['function'].get('name')
                            params = rt['function'].get('parameters', {})
                        else:
                            name = rt.get('name')
                            params = rt.get('parameters', {})
                            
                        if name in full_tools_lookup:
                            tools.append(full_tools_lookup[name])
                        else:
                            tools.append({
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "parameters": params
                                }
                            })
                    
                    scenario_name = test_input.get('scenario_name')
                    scenario_action = test_input.get('expected_tool')  # 'cancel', 'refund' 등 영문 키
                    scenario_id = test_input.get('scenario_id')
                    user_id = test_input.get('user_id', 1)
                    user_email = test_input.get('user_email', 'user@example.com')
                    
                    # Get branched or default system prompt (영문 키인 scenario_action 사용!)
                    current_system_prompt = self._get_branch_prompt(scenario_action, scenario_id, user_id, user_email)
                    
                    messages = [{'role': 'system', 'content': current_system_prompt}] if current_system_prompt else []
                    
                    dialog_content = test_input.get('dialogue') or test_input.get('messages')
                    if isinstance(dialog_content, list):
                        messages.extend(dialog_content)
                    else:
                        messages.append({'role': 'user', 'content': dialog_content})
                    
                    # task_id to serial_num (int)
                    task_id = test_input.get('task_id', f'eval_{idx+1:04d}')
                    try:
                        serial_num = int(task_id.split('_')[-1])
                    except Exception:
                        serial_num = idx + 1
                    
                    arguments = {
                        'serial_num': serial_num,
                        'messages': messages,
                        'tools': tools,
                        'ground_truth': test_input['ground_truth'],
                        'type_of_output': test_input.get('type_of_output', 'call'),
                        'acceptable_arguments': test_input.get('acceptable_arguments', {}),
                        'user_id': user_id,
                        'scenario_name': scenario_name,
                        'scenario_id': scenario_id,
                        'temperature': self.temperature,
                        'tool_choice': 'auto'
                    }
                    api_request_list.append(DialogRequestFormatter(**arguments).to_dict())
                    continue

                # Original format handling
                # test_input keys = ['dialog_num', 'tools_count', 'tools', 'turns', 'user_id', 'user_email']
                tools = test_input['tools']
                
                # IMPORTANT: Get scenario info from top-level test_input
                scenario_name = test_input.get('scenario_name')
                scenario_id = test_input.get('scenario_id')
                current_user_id = test_input.get("user_id", 1)
                current_user_email = test_input.get("user_email", "test@test.com")
                
                for turn in test_input['turns']:
                    # Re-verify user_id from turn if exists
                    turn_user_id = turn.get('user_id', current_user_id)
                    
                    current_system_prompt = self._get_branch_prompt(scenario_name, scenario_id, turn_user_id, current_user_email)
                    
                    messages = [{'role': 'system', 'content': current_system_prompt}] if current_system_prompt else []
                    messages.extend(turn['query'])
                    
                    arguments = {key: turn[key] for key in ['serial_num', 'ground_truth', 'type_of_output']}
                    arguments['acceptable_arguments'] = turn.get('acceptable_arguments', {})
                    arguments['tools'] = tools
                    arguments['messages'] = messages
                    arguments['user_id'] = turn_user_id
                    arguments['scenario_name'] = scenario_name
                    arguments['scenario_id'] = scenario_id
                    arguments['temperature'] = self.temperature
                    arguments['tool_choice'] = 'auto'
                    api_request_list.append(DialogRequestFormatter(**arguments).to_dict())
        # 3. write requests jsonl file
        with open(kwargs['request_file_path'], 'w', encoding='utf-8-sig') as fi:
            for api_request in api_request_list:
                fi.write(f"{json.dumps(api_request, ensure_ascii=False)}\n")
        return api_request_list


class SingleCallPayloadCreator(AbstractPayloadCreator):
    def __init__(self, temperature, system_prompt_file_path):
        super().__init__(temperature, 500, system_prompt_file_path)

    @type_check(validate_params)
    def create_payload(self, **kwargs):
        # kwargs keys = ['input_file_path', 'request_file_path', 'reset', 'tools_type']
        test_set = utils.load_to_jsonl(kwargs['input_file_path'])
        # update input file max_size
        self.max_size = len(test_set)
        # 1. check to cached file
        api_request_list = []
        if kwargs['reset'] is False:
            api_request_list = self.load_cached_payload(kwargs['request_file_path'])
            if len(api_request_list) == self.max_size:
                return api_request_list
        else:
            print("[[reset!! create requests jsonl file]]")
        # 2. create requests json list
        for idx, test_input in enumerate(tqdm(test_set)):
            # test_input keys = ['function_num', 'function_name', 'function_info', 'query',
            #                    'ground_truth', 'acceptable_arguments', 'tools']
            # tools type으로 filtering
            tools_list = []
            tools_type = kwargs['tools_type']
            for t in test_input['tools']:
                if tools_type == 'all' or t['type'] == tools_type:
                    tools_list.append((t['content'], t['type']))
            for q_idx, query in enumerate(test_input['query']):
                messages = [{'role': 'system', 'content': self.system_prompt}, {'role': 'user', 'content': query['content']}]
                for tools, t_type in tools_list:
                    arguments = {
                        'serial_num': query['serial_num'],
                        'messages': messages,
                        'temperature': self.temperature,
                        'tool_choice': 'auto',
                        'tools': tools,
                        'tools_type': t_type,
                        'acceptable_arguments': test_input['acceptable_arguments'][q_idx]['content'],
                        'ground_truth': test_input['ground_truth'][q_idx]['content'],
                    }
                    api_request_list.append(SingleCallRequestFormatter(**arguments).to_dict())
        # 3. write requests jsonl file
        with open(kwargs['request_file_path'], 'w', encoding='utf-8-sig') as fi:
            for api_request in api_request_list:
                fi.write(f"{json.dumps(api_request, ensure_ascii=False)}\n")
        print(f"[[model request file : {kwargs['request_file_path']}]]")
        return api_request_list


class PayloadCreatorFactory:
    """
    A factory class for creating specific payload creators based on the type of evaluation.
    """
    @staticmethod
    def get_payload_creator(evaluation_type, temperature, system_prompt_file_path=None):
        """
        Returns an instance of a payload creator based on the specified evaluation type.

        Parameters:
            evaluation_type (str): The type of evaluation, which determines the type of payload creator.
            temperature (float): The variability setting for the model's responses used in the payload.
            system_prompt_file_path (str, optional): Path to the file containing the system prompt for payloads.

        Returns:
            A payload creator instance appropriate for the given evaluation type.

        Raises:
            ValueError: If the specified evaluation type is not supported.
        """
        if evaluation_type == 'common':
            return CommonPayloadCreator(temperature)
        elif evaluation_type == 'dialog':
            return DialogPayloadCreator(temperature, system_prompt_file_path)
        elif evaluation_type == 'singlecall':
            return SingleCallPayloadCreator(temperature, system_prompt_file_path)
        else:
            raise ValueError("Unsupported evaluation type")
