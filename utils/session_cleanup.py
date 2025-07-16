# utils/session_cleanup.py
from datetime import datetime, timedelta, timezone
import logging
import os

time_hours = int(os.environ.get("time_hours", 24))
time_minutes = int(os.environ.get("time_minutes", 1))

def clean_old_sessions(container):
    """Cierra sesiones sin respuesta en 1 minuto o con más de 24 horas abiertas."""
    now = datetime.now(timezone.utc)
    one_minute_ago = now - timedelta(minutes=time_minutes)
    one_day_ago = now - timedelta(hours=time_hours)

    query = "SELECT * FROM c WHERE c.sessionStatus = 'opened'"
    conversations = list(container.query_items(query, enable_cross_partition_query=True))

    for convo in conversations:
        messages = convo.get("messages", [])
        last_user_message = next((m for m in reversed(messages) if m["role"] == "user"), None)

        last_user_time = (
            datetime.fromisoformat(last_user_message["date"])
            if last_user_message
            else datetime.fromisoformat(convo["createdAt"])
        )
        created_at = datetime.fromisoformat(convo["createdAt"])

        should_close = last_user_time < one_minute_ago or created_at < one_day_ago
        if should_close:
            logging.info(f"Cerrando conversación {convo['id']} por inactividad o antigüedad.")
            convo["sessionStatus"] = "closed"
            convo["updatedAt"] = now.isoformat()
            container.upsert_item(convo)
