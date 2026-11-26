"""SKILL.md discovery; skills supply instructions, never implicit shell execution."""
import re
import json


class Skills:
    def __init__(self, root):
        self.root = root / 'skills/builtin'

    def list(self):
        result = []
        for file in sorted(self.root.glob('*/SKILL.md')):
            if not file.resolve().is_relative_to(self.root.resolve()):
                continue
            text = file.read_text(encoding='utf-8')
            heading = re.search(r'^#\s+(.+)', text, re.M)
            result.append({'id': file.parent.name, 'name': heading.group(1) if heading else file.parent.name})
        return result

    def read(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', identifier):
            raise ValueError('技能标识无效')
        file = (self.root / identifier / 'SKILL.md').resolve()
        if not file.is_relative_to(self.root.resolve()) or not file.is_file():
            raise ValueError('技能不存在')
        text = file.read_text(encoding='utf-8')
        if len(text) > 50000:
            raise ValueError('技能指令过长，请拆分为引用资料')
        return text

    def create(self, identifier, text):
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', identifier):
            raise ValueError('技能标识只能包含字母、数字、短横线和下划线')
        if not isinstance(text, str) or not text.strip() or len(text) > 50000:
            raise ValueError('请输入技能规范，最多50000字')
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / identifier
        if not target.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('技能目录无效')
        try:
            target.mkdir()
        except FileExistsError:
            raise ValueError('该技能已存在，不会覆盖') from None
        try:
            (target / 'SKILL.md').write_text(text, encoding='utf-8')
        except BaseException:
            target.rmdir(); raise
        return {'id': identifier}

    def catalog(self):
        path = self.root.parents[1] / 'docs/easel-skill-catalog.json'
        installed = {item['id'] for item in self.list()}
        rows = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
        return [{**row, 'installed': row['id'] in installed} for row in rows]
