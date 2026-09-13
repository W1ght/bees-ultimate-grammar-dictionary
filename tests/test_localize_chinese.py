import json

from scripts.localize_chinese import _cache_key, localize_file, strip_english


def test_strip_english_keeps_japanese_lines():
    value = "A handbook of grammar patterns\n\n〜ている状態を表す。"
    assert strip_english(value) == "〜ている状態を表す。"


def test_english_source_gets_separate_cached_chinese_channel(tmp_path):
    artifact = tmp_path / "dojg.json"
    artifact.write_text(
        json.dumps(
            {
                "source": "dojg",
                "stats": {},
                "points": [
                    {
                        "meaning": "to be able to",
                        "examples": [{"japanese": "泳ぐことができる。", "english": "I can swim."}],
                        "provenance": {},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cache = {
        "version": 1,
        "entries": {
            _cache_key("dojg", "meaning", "to be able to"): {"translation": "能够；可以"},
            _cache_key("dojg", "example:0", "I can swim."): {"translation": "我会游泳。"},
        },
    }
    localize_file(artifact, cache=cache, api_key="test", model="test")
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    point = payload["points"][0]
    assert point["meaning"] == "to be able to"
    assert point["provenance"]["translationZh"]["meaning"] == "能够；可以"
    assert point["provenance"]["translationZh"]["examples"] == {"泳ぐことができる。": "我会游泳。"}


def test_japanese_english_source_drops_english(tmp_path):
    artifact = tmp_path / "hjgp_en.json"
    artifact.write_text(
        json.dumps(
            {
                "source": "hjgp_en",
                "stats": {},
                "points": [
                    {
                        "meaning": "English explanation",
                        "explanation": "English paragraph\n日本語の説明",
                        "examples": [{"japanese": "日本語です。", "english": "It is Japanese."}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    localize_file(artifact, cache={"version": 1, "entries": {}}, api_key="", model="")
    point = json.loads(artifact.read_text(encoding="utf-8"))["points"][0]
    assert point["meaning"] is None
    assert point["explanation"] == "日本語の説明"
    assert point["examples"][0]["english"] is None
