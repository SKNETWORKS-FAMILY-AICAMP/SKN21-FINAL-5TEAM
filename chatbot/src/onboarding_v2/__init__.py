def run_onboarding_generation_v2(*args, **kwargs):
    from .engine import run_onboarding_generation_v2 as implementation

    return implementation(*args, **kwargs)

__all__ = ["run_onboarding_generation_v2"]
