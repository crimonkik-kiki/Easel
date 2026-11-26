DESCRIPTOR = {
    'id': 'brief', 'name': '任务简报',
    'action_label': '生成简报',
    'description': '把需求整理成目标、交付物、步骤与待确认事项。',
    'fields': [{'id': 'requirements', 'label': '需求内容', 'type': 'textarea'}]
}


def prompt(values):
    value = values.get('requirements', '')
    if not isinstance(value, str):
        raise ValueError('需求内容必须是文本')
    text = value.strip()
    if not text or len(text) > 20000:
        raise ValueError('请填写需求内容（最多20000字）')
    return '将下列需求整理为可执行的工作简报，列出目标、交付物、步骤和待确认事项；不要杜撰未知信息。\n\n' + text
