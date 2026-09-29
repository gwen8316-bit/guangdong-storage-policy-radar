"""Small replaceable provider adapter; never logs credentials or HTTP bodies."""
import json
import os
import urllib.error
import urllib.request


class DeepSeek:
    def __init__(self, model, max_tokens=1600):
        self.model = model
        self.max_tokens = max_tokens
        self.key = os.environ.get('DEEPSEEK_API_KEY')
        if not self.key:
            raise RuntimeError('Missing DEEPSEEK_API_KEY; configure the repository Actions secret')

    def complete(self, system, text):
        payload = {'model': self.model, 'messages': [
            {'role': 'system', 'content': system}, {'role': 'user', 'content': text}],
            'response_format': {'type': 'json_object'}, 'max_tokens': self.max_tokens,
            'thinking': {'type': 'disabled'}, 'stream': False}
        request = urllib.request.Request('https://api.deepseek.com/chat/completions',
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'DeepSeek HTTP {exc.code}; no automatic retry') from None
        except (OSError, ValueError):
            raise RuntimeError('DeepSeek network/response error; no automatic retry') from None
        choice = result['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ValueError('AI response incomplete')
        return json.loads(choice['message']['content']), result.get('usage', {})
