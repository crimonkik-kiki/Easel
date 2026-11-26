"""热点雷达回归测试：各平台响应格式归一化 + 取不到数据要能被识别出来。

背景（2026-10-01）：热点雷达六个平台里三个是空的——B站其实是解析器的锅（备用源返回 50 条
纯字符串数组，而解析器只认对象数组，全被丢掉），知乎/头条则是压根没有备用源且主源被限流。
这个文件守住两件事：各家格式都解析得出来、以及"取不到"要和"真的没数据"分开。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import app as web  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_trend_cache(monkeypatch):
    monkeypatch.setattr(web, "_TREND_CACHE", {})
    monkeypatch.setattr(web, "_TREND_INFLIGHT", {})
    monkeypatch.setattr(web, "_TREND_RETRY_AFTER", {})


# ---- 各家响应格式 ----

def test_parse_hot_handles_plain_string_array():
    """xxapi 的 B站热榜：data 就是一串标题字符串，没有对象包着。"""
    items = web._parse_hot({"code": 200, "data": ["凉哈皮谈首登亚运解说台", "   ", "holymoly亚运金牌"]})
    assert [i["title"] for i in items] == ["凉哈皮谈首登亚运解说台", "holymoly亚运金牌"]
    assert all(i["hot"] == "" and i["url"] == "" for i in items)


def test_parse_hot_handles_capitalized_fields():
    """头条官方热榜：Title / HotValue / Url 全是大写开头，热度还会是数字。"""
    items = web._parse_hot({"data": [
        {"ClusterId": 1, "Title": "农民交公粮能否视同缴社保", "HotValue": 1234567,
         "Url": "https://www.toutiao.com/trending/1/"},
    ]})
    assert items == [{"title": "农民交公粮能否视同缴社保", "hot": "1234567",
                      "url": "https://www.toutiao.com/trending/1/"}]


def test_parse_hot_handles_nested_target_and_rewrites_zhihu_url():
    """知乎官方热榜：正文在 target 里，链接给的是 api.zhihu.com，要点开得换成网页地址。"""
    items = web._parse_hot({"data": [
        {"type": "hot_list_feed", "card_id": "Q_1",
         "target": {"id": 2088649572151194406, "title": "迪拜航空客机返航",
                    "url": "https://api.zhihu.com/questions/2088649572151194406",
                    "metrics_area": {"text": "387 万热度"}}},
    ]})
    assert items == [{"title": "迪拜航空客机返航", "hot": "387 万热度",
                      "url": "https://www.zhihu.com/question/2088649572151194406"}]


def test_parse_hot_keeps_original_shape_working():
    """60s 那套老格式（data 直接是对象数组）不能被新写法改坏。"""
    items = web._parse_hot({"data": [{"title": "迪拜航空确认航班发生事故", "hot": "118万",
                                      "url": "https://s.weibo.com/x"}]})
    assert items == [{"title": "迪拜航空确认航班发生事故", "hot": "118万", "url": "https://s.weibo.com/x"}]


def test_parse_hot_accepts_nested_data_wrapper():
    items = web._parse_hot({"data": {"list": [{"word": "热词", "num": 42}]}})
    assert items == [{"title": "热词", "hot": "42", "url": ""}]


@pytest.mark.parametrize("bad", [
    {}, {"data": None}, {"data": "不是列表"}, {"data": [1, 2, 3]}, {"data": [{"hot": "1"}]}, [],
])
def test_parse_hot_returns_empty_on_junk(bad):
    """垃圾/空响应要安静地返回空列表，不能抛异常（抛了整条平台就断）。"""
    assert web._parse_hot(bad) == []


def test_trend_web_url_passes_through_other_urls():
    assert web._trend_web_url("") == ""
    assert web._trend_web_url("https://s.weibo.com/x") == "https://s.weibo.com/x"
    assert web._trend_web_url("https://api.zhihu.com/questions/abc") == "https://api.zhihu.com/questions/abc"


# ---- 源表本身 ----

def test_every_platform_has_a_source():
    """每个能选中的平台都要有主源，别出现"按钮在但没人给它取数据"。"""
    assert set(web.TREND_SOURCES) == set(web.TREND_LABELS)
    for pf, (primary, backup) in web.TREND_SOURCES.items():
        assert primary and primary.startswith("http"), f"{pf} 缺主源"
        if backup:
            assert backup.startswith("http")


# ---- 接口：取不到 vs 真的没有 ----

def test_trends_marks_unavailable_platform(monkeypatch):
    """/api/trends 要给每个平台带 ok 标：空列表＝这个平台取不到，不是"今天没热搜"。"""
    web._TREND_CACHE.clear()
    monkeypatch.setattr(web, "_fetch_platform",
                        lambda pf: [{"title": f"{pf} 的头条", "hot": "", "url": ""}] if pf == "weibo" else [])
    data = asyncio.run(web.api_trends("weibo,bilibili", 15))
    by_pf = {g["platform"]: g for g in data["trends"]}
    assert by_pf["weibo"]["ok"] is True and len(by_pf["weibo"]["items"]) == 1
    assert by_pf["bilibili"]["ok"] is False and by_pf["bilibili"]["items"] == []


def test_trends_ignores_unknown_platform(monkeypatch):
    """乱传平台名不能把接口带崩，也不能凭空多出渠道。"""
    web._TREND_CACHE.clear()
    monkeypatch.setattr(web, "_fetch_platform", lambda pf: [])   # 测试不打真实网络
    data = asyncio.run(web.api_trends("weibo,不存在", 5))
    assert [g["platform"] for g in data["trends"]] == ["weibo"]
    assert [g["label"] for g in data["trends"]] == ["微博"]


@pytest.mark.parametrize("primary_result", [None, {"data": []}, {"data": "invalid"}])
def test_fetch_platform_falls_back_on_error_or_empty_response(monkeypatch, primary_result):
    primary, backup = web.TREND_SOURCES["weibo"]
    calls = []

    def fetch(url):
        calls.append(url)
        if url == primary:
            if primary_result is None:
                raise OSError("unavailable")
            return primary_result
        return {"data": [{"title": "备用热点"}]}

    monkeypatch.setattr(web, "_http_get_json", fetch)
    assert web._fetch_platform("weibo") == [{"title": "备用热点", "hot": "", "url": ""}]
    assert calls == [primary, backup]


def test_trends_reuses_cached_items_when_all_sources_fail(monkeypatch):
    items = [{"title": "缓存热点", "hot": "", "url": ""}]
    web._TREND_CACHE["weibo"] = (0, items)
    monkeypatch.setattr(web, "_fetch_platform", lambda platform: [])
    data = asyncio.run(web.api_trends("weibo", 15))
    assert data["trends"][0]["items"][0]['title'] == items[0]['title']
    assert data['trends'][0]['stale'] is True
    assert data['trends'][0]['updated'] == data['updated'] == 0
    assert data["trends"][0]["ok"] is True


def test_parse_deep_wrappers_and_new_heat_field():
    assert web._parse_hot({'code': 200, 'data': {'data': {'items': [
        {'title': '测试热点', 'hot_value_desc': '123 万热度', 'link': 'https://example.invalid/news'}]}}}) == [
        {'title': '测试热点', 'hot': '123 万热度', 'url': 'https://example.invalid/news'}]
    assert web._parse_hot({'code': 403, 'data': [{'title': '失败占位数据'}]}) == []


def test_trends_returns_more_than_thirty_and_marks_search_links(monkeypatch):
    rows = [{'title': f'热词{i}', 'hot': '', 'url': ''} for i in range(52)]
    monkeypatch.setattr(web, '_fetch_platform', lambda pf: rows)
    group = asyncio.run(web.api_trends('bilibili', 100))['trends'][0]
    assert len(group['items']) == group['total'] == 52
    assert group['missing_hot'] == group['search_links'] == 52
    assert group['items'][0]['url_kind'] == 'search'
    assert group['items'][0]['url'].startswith('https://search.bilibili.com/all?keyword=')


def test_primary_short_list_uses_longer_backup(monkeypatch):
    primary, backup = web.TREND_SOURCES['weibo']
    def fetch(url):
        return {'data': [{'title': f'热词{i}'} for i in range(2 if url == primary else 50)]}
    monkeypatch.setattr(web, '_http_get_json', fetch)
    assert len(web._fetch_platform('weibo')) == 50


def test_parallel_platforms_preserve_order_and_single_inflight(monkeypatch):
    from threading import Barrier
    barrier = Barrier(2, timeout=3)
    calls = []
    def fetch(pf):
        calls.append(pf)
        barrier.wait()
        return [{'title': pf, 'hot': '1', 'url': 'https://example.invalid/'}]
    monkeypatch.setattr(web, '_fetch_platform', fetch)
    async def scenario():
        first, second = await asyncio.gather(web.api_trends('weibo,douyin,weibo', 100),
                                             web.api_trends('weibo,douyin', 100))
        assert first == second
        assert [row['platform'] for row in first['trends']] == ['weibo', 'douyin']
        assert sorted(calls) == ['douyin', 'weibo']
        assert web._TREND_INFLIGHT == {}
    asyncio.run(scenario())


def test_one_platform_exception_does_not_drop_other_groups(monkeypatch):
    def fetch(pf):
        if pf == 'weibo':
            raise OSError('offline')
        return [{'title': '可用热点', 'hot': '1', 'url': 'https://example.invalid/'}]
    monkeypatch.setattr(web, '_fetch_platform', fetch)
    groups = asyncio.run(web.api_trends('weibo,douyin', 100))['trends']
    assert len(groups) == 2 and not groups[0]['ok'] and groups[1]['ok']


def test_failed_source_retry_backoff_and_unsafe_urls(monkeypatch):
    calls = []
    monkeypatch.setattr(web, '_fetch_platform', lambda pf: calls.append(pf) or [])
    async def scenario():
        await web.api_trends('weibo', 100)
        await web.api_trends('weibo', 100)
    asyncio.run(scenario())
    assert calls == ['weibo']
    links = web._complete_trend_links('weibo', [{'title': '话题', 'hot': '0', 'url': 'javascript:alert(1)'}])
    assert links[0]['url_kind'] == 'search'
