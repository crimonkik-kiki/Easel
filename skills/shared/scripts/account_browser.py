"""Open an account's existing Edge profile for manual creator-center work."""
from account_network import browser_options as account_browser_options
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

URLS = {
    'xiaohongshu': 'https://creator.xiaohongshu.com/new/home',
    'douyin': 'https://creator.douyin.com/',
    'kuaishou': 'https://cp.kuaishou.com/',
    'weixin-channels': 'https://channels.weixin.qq.com/',
    'zhihu': 'https://www.zhihu.com/creator',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=URLS, required=True)
    parser.add_argument('--profile', required=True)
    args = parser.parse_args()
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(Path(args.profile).resolve()), **account_browser_options(dict(channel='msedge', headless=False,
            no_viewport=True, args=['--start-maximized'])))
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(URLS[args.platform], wait_until='commit', timeout=60000)
        while context.pages:
            try:
                context.pages[0].wait_for_timeout(500)
            except Exception:
                if not context.pages:
                    break
        context.close()


if __name__ == '__main__':
    main()
