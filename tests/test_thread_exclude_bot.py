from staffing_agent.thread_context import exclude_bot_user_messages


def test_exclude_bot_user_messages():
    bot = "U_BOT123"
    msgs = [
        {"user": "U_HUMAN", "text": "hello"},
        {"user": bot, "text": "bot reply"},
        {"user": "U_HUMAN2", "text": "follow up"},
    ]
    out = exclude_bot_user_messages(msgs, bot)
    assert len(out) == 2
    assert out[0]["text"] == "hello"
    assert out[1]["text"] == "follow up"


def test_exclude_bot_empty_id_noop():
    msgs = [{"user": "U1", "text": "a"}]
    assert exclude_bot_user_messages(msgs, "") == msgs
