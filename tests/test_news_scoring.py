from src.data.news_scoring import score_headline, score_news_batch


def test_bullish_headline_is_tagged_with_matched_keywords():
    result = score_headline("Foxconn Sales Jump 40% as AI Server Demand Accelerates")
    assert result["tone"] == "bullish"
    assert "jump" in result["matched_keywords"]
    assert any("accelerat" in kw for kw in result["matched_keywords"])


def test_bearish_headline_is_tagged_with_matched_keywords():
    result = score_headline("Company Downgraded After Lawsuit and Profit Warning")
    assert result["tone"] == "bearish"
    assert "downgraded" in result["matched_keywords"]
    assert "lawsuit" in result["matched_keywords"]


def test_headline_with_no_matching_keywords_is_neutral():
    result = score_headline("Taiwan to launch finance-sector AI model project")
    assert result["tone"] == "neutral"
    assert result["matched_keywords"] == []


def test_headline_with_equal_bullish_and_bearish_hits_resolves_neutral():
    # "surge" (bullish) and "plunge" (bearish) both present -- a tie should
    # not silently pick a direction.
    result = score_headline("Stock Surges Then Plunges in Volatile Session")
    assert result["tone"] == "neutral"


def test_empty_or_missing_title_is_neutral():
    assert score_headline("")["tone"] == "neutral"
    assert score_headline(None)["tone"] == "neutral"


def test_score_news_batch_empty_list_is_neutral_zero():
    summary = score_news_batch([])
    assert summary == {"score": 0.0, "bullish_count": 0, "bearish_count": 0}


def test_score_news_batch_tags_items_in_place_and_aggregates():
    news = [
        {"title": "Foxconn Sales Jump 40% as AI Server Demand Accelerates"},
        {"title": "Company Downgraded After Lawsuit and Profit Warning"},
        {"title": "Taiwan to launch finance-sector AI model project"},
    ]
    summary = score_news_batch(news)
    assert news[0]["tone"] == "bullish"
    assert news[1]["tone"] == "bearish"
    assert news[2]["tone"] == "neutral"
    assert summary == {"score": 0.0, "bullish_count": 1, "bearish_count": 1}


def test_score_news_batch_all_bullish_scores_positive_one():
    news = [
        {"title": "Stock Surges to Record High"},
        {"title": "Company Beats Earnings Expectations"},
    ]
    summary = score_news_batch(news)
    assert summary["score"] == 1.0
    assert summary["bullish_count"] == 2
    assert summary["bearish_count"] == 0
