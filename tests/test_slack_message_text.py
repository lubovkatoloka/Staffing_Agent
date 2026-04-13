from staffing_agent.thread_context import slack_message_plain_text


def test_plain_text_top_level():
    assert slack_message_plain_text({"text": "  hello  "}) == "hello"


def test_plain_text_from_blocks():
    m = {
        "text": "",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Line from block"},
            }
        ],
    }
    assert "Line from block" in slack_message_plain_text(m)
