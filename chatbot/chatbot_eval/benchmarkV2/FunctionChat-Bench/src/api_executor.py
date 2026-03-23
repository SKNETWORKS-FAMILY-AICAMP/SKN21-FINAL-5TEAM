import sys
import json
import openai
import logging
import traceback
import time
from langsmith import wrappers

try:
    from mistralai.client import MistralClient
    from mistralai.exceptions import MistralAPIException
except ImportError:
    MistralClient = None
    MistralAPIException = None


try:
    import vertexai
except ImportError:
    vertexai = None


from src.gemini_utils import (
    convert_messages_gemini,
    convert_tools_gemini,
    convert_gemini_to_response,
    call_gemini_model
)

from src.utils import convert_tools_alphachat

try:
    import qwen_agent
except ImportError:
    qwen_agent = None


logger = logging.getLogger(__name__)

class AbstractModelAPIExecutor:
    """
    A base class for model API executors that defines a common interface for making predictions.
    This class should be inherited by specific API executor implementations.

    Attributes:
        model (str): The model identifier.
        api_key (str): The API key for accessing the model.
    """
    def __init__(self, model, api_key):
        logger.info(f"model: {model}")
        logger.info(f"api_key: {api_key}")
        self.model = model
        self.api_key = api_key

    def predict(self):
        raise NotImplementedError("Subclasses must implement this method.")
    
    def _call_with_retry(self, func, *args, **kwargs):
        max_retries = kwargs.get('max_retries', 3)
        for attempt in range(max_retries):
            try:
                response = func(*args, **kwargs)
                response = response.model_dump()
                return response
            except Exception as e:
                logger.warning(f"API 호출 실패 (시도 {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    logger.error("최대 재시도 횟수 초과, 예외 발생")
                    print(json.dumps(kwargs, ensure_ascii=False, indent=2))
                    raise
            time.sleep(0.1)

    def _parse_response(self, response):
        if isinstance(response, dict) and 'choices' in response:
            return response['choices'][0]['message']
        return response

class OpenaiModelAzureAPI(AbstractModelAPIExecutor):
    def __init__(self, model, api_key, api_base, api_version):
        super().__init__(model, api_key)
        self.raw_client = openai.AzureOpenAI(azure_endpoint=api_base,
                                         api_key=api_key,
                                         api_version=api_version)
        self.wrapped_client = wrappers.wrap_openai(openai.AzureOpenAI(azure_endpoint=api_base,
                                         api_key=api_key,
                                         api_version=api_version))
        self.raw_completion = self.raw_client.chat.completions.create
        self.wrapped_completion = self.wrapped_client.chat.completions.create

    def predict(self, api_request):
        use_trace = api_request.get('trace', True)
        completion_func = self.wrapped_completion if use_trace else self.raw_completion
        
        response = self._call_with_retry(
            completion_func,
            model=self.model,
            temperature=api_request['temperature'],
            messages=api_request['messages']
        )
        response = self._parse_response(response)
        return response


class OpenaiModelAPI(AbstractModelAPIExecutor):
    def __init__(self, model, api_key, base_url='https://api.openai.com/v1', use_eval=False):
        super().__init__(model, api_key)
        self.raw_client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.wrapped_client = wrappers.wrap_openai(openai.OpenAI(api_key=api_key, base_url=base_url))
        self.raw_completion = self.raw_client.chat.completions.create
        self.wrapped_completion = self.wrapped_client.chat.completions.create
        
        if use_eval is True:
            self.predict = self.predict_eval
        else:
            self.predict = self.predict_tool

    def models(self):
        return self.raw_client.models.list()

    def predict_tool(self, api_request):
        tools = api_request['tools']
        if tools and (self.model.startswith('gemini') or self.model.startswith('claude')):
            tools = convert_tools_alphachat(tools)

        use_trace = api_request.get('trace', True)
        completion_func = self.wrapped_completion if use_trace else self.raw_completion

        response = self._call_with_retry(
            completion_func,
            model=self.model,
            temperature=api_request['temperature'],
            messages=api_request['messages'],
            tools=tools
        )
        response_output = self._parse_response(response)
        return response_output

    def predict_eval(self, api_request):
        use_trace = api_request.get('trace', True)
        completion_func = self.wrapped_completion if use_trace else self.raw_completion
        
        response = None
        while True:
            try:
                response = completion_func(
                    model=self.model,
                    temperature=api_request['temperature'],
                    messages=api_request['messages']
                )
                response = response.model_dump()
                break
            except KeyError as e:
                traceback.print_exc()
                print(json.dumps(api_request['messages'], ensure_ascii=False))
                sys.exit(1)
            except Exception as e:
                traceback.print_exc()
                print(json.dumps(api_request['messages'], ensure_ascii=False))
                raise e
        return response


class SolarModelAPI(AbstractModelAPIExecutor):
    def __init__(self, model, api_key, base_url):
        super().__init__(model, api_key)
        self.raw_client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.wrapped_client = wrappers.wrap_openai(openai.OpenAI(base_url=base_url, api_key=api_key))
        self.raw_completion = self.raw_client.chat.completions.create
        self.wrapped_completion = self.wrapped_client.chat.completions.create

    def predict(self, api_request):
        use_trace = api_request.get('trace', True)
        completion_func = self.wrapped_completion if use_trace else self.raw_completion
        
        response = self._call_with_retry(
            completion_func,
            model=self.model,
            temperature=api_request['temperature'],
            messages=api_request['messages'],
            tools=api_request['tools']
        )
        response_output = self._parse_response(response)
        return response_output


class MistralModelAPI(AbstractModelAPIExecutor):
    def __init__(self, model, api_key):
        """
        Initialize the MistralModelAPI class.

        Parameters:
        model (str): The name of the model to use.
        api_key (str): The API key for authenticating with OpenAI.
        """
        super().__init__(model, api_key)
        self.client = MistralClient(api_key=api_key)
        self.openai_chat_completion = self.client.chat

    def remove_content_for_toolcalls(self, messages):
        new_messages = []
        for msg in messages:
            if msg['role'] == 'assistant' and msg.get('content', None) and msg.get('tool_calls', None):
                msg['content'] = ""
            new_messages.append(msg)
        return new_messages

    def predict(self, api_request):
        response = None
        try_cnt = 0
        while True:
            try:
                response = self.openai_chat_completion(
                    model=self.model,
                    temperature=api_request['temperature'],
                    max_tokens=32768,
                    messages=api_request['messages'],
                    tools=api_request['tools']
                )
                response = response.model_dump()
                break
            except MistralAPIException as e:
                msg = json.loads(str(e).split('Message:')[1]).get('message')
                if msg == 'Assistant message must have either content or tool_calls, but not both.':
                    api_request['messages'] = self.remove_content_for_toolcalls(api_request['messages'])
                    print(f"[error] {msg}")
                    print(json.dumps(api_request['messages'], ensure_ascii=False))
                print(f".. retry api call .. {try_cnt} {msg} {msg == 'Assistant message must have either content or tool_calls, but not both.'}")
                try_cnt += 1
            except Exception as e:
                traceback.print_exc()
                print(json.dumps(api_request['messages'], ensure_ascii=False))
                raise e
        response_output = self._parse_response(response)
        return response_output


class InhouseModelAPI(AbstractModelAPIExecutor):
    def __init__(self, model, api_key, base_url, served_model_name):
        super().__init__(model, api_key)
        self.raw_client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.wrapped_client = wrappers.wrap_openai(openai.OpenAI(base_url=base_url, api_key=api_key))
        self.raw_completion = self.raw_client.chat.completions.create
        self.wrapped_completion = self.wrapped_client.chat.completions.create
        self.served_model_name = served_model_name

    def models(self):
        return self.raw_client.models.list()

    def predict(self, api_request):
        use_trace = api_request.get('trace', True)
        completion_func = self.wrapped_completion if use_trace else self.raw_completion
        
        response = self._call_with_retry(
            completion_func,
            model=self.served_model_name,
            temperature=api_request['temperature'],
            messages=api_request['messages'],
            tools=api_request['tools'],
            timeout=30  # 30초 타임아웃
        )
        response_output = self._parse_response(response)
        return response_output


class Qwen2ModelAPI(AbstractModelAPIExecutor):
    def __init__(self, model, api_key, base_url, served_model_name):
        super().__init__(model, api_key)
        if served_model_name is not None:
            model = served_model_name
        self.client = qwen_agent.llm.get_chat_model({
            'model': served_model_name,
            'model_server': base_url,
            'api_key': api_key
        })

    def predict(self, api_request):
        messages = api_request['messages']
        tools = [tool['function'] for tool in api_request['tools']]
        responses = []

        for idx, msg in enumerate(messages):
            if msg['role'] == 'tool':
                messages[idx]['role'] = 'function'
            if msg['role'] == 'assistant' and 'tool_calls' in msg:
                messages[idx]['function_call'] = msg['tool_calls'][0]['function']
        for responses in self.client.chat(messages=messages, functions=tools, stream=True):
            continue
        response = responses[0]
        tools = None
        if 'function_call' in response:
            tools = [{'id': "qwen2-functioncall-random-id", 'function': response['function_call'], 'type': "function", 'index': None}]
        return {
            "content": response['content'],
            "role": response['role'],
            "function_call": None,
            "tool_calls": tools,
            "tool_call_id": None,
            "name": None
        }


class GeminiModelAPI(AbstractModelAPIExecutor):
    def __init__(self, model, gcloud_project_id, gcloud_location):
        """
        Initialize the GeminiModelAPI class.

        Parameters:
        model (str): The name of the model to use.
        gcloud_project_id (str): The Google Cloud project ID, required for models hosted on Google Cloud.
        gcloud_location (str): The location of the Google Cloud project, required for models hosted on Google Cloud.
        """
        super().__init__(model, None)
        vertexai.init(project=gcloud_project_id, location=gcloud_location)

    def predict(self, api_request):
        try_cnt = 0
        response = None

        gemini_temperature = api_request['temperature']
        gemini_system_instruction, gemini_messages = convert_messages_gemini(api_request['messages'])
        gemini_tools = convert_tools_gemini(api_request['tools'])

        while True:
            try:
                response = call_gemini_model(
                    gemini_model=self.model,
                    gemini_temperature=gemini_temperature,
                    gemini_system_instruction=gemini_system_instruction,
                    gemini_tools=gemini_tools,
                    gemini_messages=gemini_messages)
                gemini_response = response['candidates'][0]
                if "content" not in gemini_response and gemini_response["finish_reason"] == "SAFETY":
                    response_output = {"role": "assistant", "content": None, "tool_calls": None}
                else:
                    response_output = convert_gemini_to_response(gemini_response["content"])
            except Exception as e:
                traceback.print_exc()
                print(json.dumps(api_request['messages'], ensure_ascii=False))
                raise e
            else:
                break
        return response_output


class APIExecutorFactory:
    """
    A factory class to create model API executor instances based on the model name.
    """

    @staticmethod
    def get_model_api(model_name, api_key=None, served_model_name=None, base_url=None, gcloud_project_id=None, gcloud_location=None):
        """
        Creates and returns an API executor for a given model by identifying the type of model and initializing the appropriate API class.

        Parameters:
            model_name (str): The name of the model to be used. It determines which API class is instantiated.
            api_key (str, optional): The API key required for authentication with the model's API service.
            served_model_name (str, optional): served model name.
            base_url (str, optional): The base URL of the API service for the model.
            gcloud_project_id (str, optional): The Google Cloud project ID, required for models hosted on Google Cloud.
            gcloud_location (str, optional): The location of the Google Cloud project, required for models hosted on Google Cloud.

        Returns:
            An instance of an API executor for the specified model.

        Raises:
            ValueError: If the model name is not supported.

        The method uses the model name to determine which API executor class to instantiate and returns an object of that class.
        """
        if model_name == 'inhouse' or model_name.startswith('qwen3'):  # In-house developed model
            return InhouseModelAPI(model_name, api_key, base_url=base_url, served_model_name=served_model_name)
        if model_name == 'inhouse-local':  # In-house developed model
            return InhouseModelAPI(model_name, api_key, base_url=base_url, served_model_name=served_model_name)
        elif model_name.lower().startswith('qwen2'):  # Upstage developed model
            return Qwen2ModelAPI(model_name, api_key=api_key, base_url=base_url, served_model_name=served_model_name)
        elif model_name.lower().startswith('solar'):  # Upstage developed model
            return SolarModelAPI(model_name, api_key=api_key, base_url=base_url)
        elif model_name.lower().startswith('gpt'):  # OpenAI developed model
            if base_url:
                return OpenaiModelAPI(model_name, api_key, base_url=base_url)
            return OpenaiModelAPI(model_name, api_key)
        elif model_name.startswith('mistral'):  # Mistral developed model
            return MistralModelAPI(model_name, api_key)
        elif model_name.startswith('gemini'):  # Google developed model
            if base_url.startswith('http://alpha-gateway'):
                return OpenaiModelAPI(model_name, api_key, base_url)
            else:
                return GeminiModelAPI(model_name, gcloud_project_id=gcloud_project_id, gcloud_location=gcloud_location)
        elif model_name.startswith('claude') and base_url.startswith('http://alpha-gateway'):
            return OpenaiModelAPI(model_name, api_key, base_url)
        else:
            raise ValueError(f"Unsupported model name, {model_name}")
