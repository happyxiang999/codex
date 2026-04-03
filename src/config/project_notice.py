"""Shared project notice content for terminal and Web UI."""

PROJECT_NOTICE = {
    "title": "项目声明",
    "free_notice": "本项目永久免费开源，若你是付费购买，请立即退款并反馈倒卖渠道。",
    "disclaimer": (
        "免责声明：本工具仅供学习和研究使用，使用本工具产生的一切后果由使用者自行承担。"
        "请遵守相关服务条款，不要用于违法或不当用途。如有侵权，请及时联系，将第一时间处理。"
    ),
    "support_notice": "",
    "github_repo_name": "happyxiang999/codex",
    "github_repo_url": "https://github.com/happyxiang999/codex",
}


def build_terminal_notice_lines() -> list[str]:
    """Build terminal-friendly notice lines."""
    lines = [
        "=" * 72,
        PROJECT_NOTICE["title"],
        PROJECT_NOTICE["free_notice"],
        PROJECT_NOTICE["disclaimer"],
    ]
    if PROJECT_NOTICE.get("support_notice"):
        lines.append(PROJECT_NOTICE["support_notice"])
    lines.extend([
        f"GitHub 仓库 {PROJECT_NOTICE['github_repo_name']}：{PROJECT_NOTICE['github_repo_url']}",
        "=" * 72,
    ])
    return lines
