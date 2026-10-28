"""Enable Qwen only after Ollama confirms the model is installed locally."""
import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'qwen3:4b-instruct'
BASE = 'http://127.0.0.1:11434'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['qwen3:4b', 'qwen3:4b-instruct'], default=MODEL)
    model = parser.parse_args().model
    try:
        with urllib.request.urlopen(BASE + '/api/tags', timeout=5) as response:
            models = json.load(response).get('models', [])
    except (OSError, ValueError):
        raise SystemExit('本机 Ollama 服务未就绪；请先启动 ollama serve。') from None
    if model not in {item.get('name') for item in models}:
        raise SystemExit(f'本机尚无 {model}；请先运行 ollama pull {model}。')
    env = ROOT / '.env'
    lines = env.read_text(encoding='utf-8').splitlines() if env.exists() else []
    lines = [line for line in lines if not line.strip().startswith(('CI_MODEL_PROVIDER=', 'CI_MODEL_BASE_URL=', 'CI_MODEL='))]
    lines += ['CI_MODEL_PROVIDER=ollama', 'CI_MODEL_BASE_URL=' + BASE, 'CI_MODEL=' + model]
    temporary = env.with_suffix('.env.tmp')
    temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    temporary.replace(env)
    print(f'本地 {model} 已写入 .env；重启 CourseInbox 后在界面选择“模型工具调用”。')


if __name__ == '__main__':
    main()
