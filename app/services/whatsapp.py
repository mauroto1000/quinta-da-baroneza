"""
Evolution API – WhatsApp integration.
All functions are fire-and-forget; errors are logged, not raised.
"""
import logging
import httpx
from sqlalchemy.orm import Session
from app import models
from app.deps import get_system_config

logger = logging.getLogger(__name__)


def _get_client_config(db: Session) -> dict:
    return {
        "url": get_system_config(db, "evolution_api_url"),
        "key": get_system_config(db, "evolution_api_key"),
        "instance": get_system_config(db, "evolution_instance"),
    }


def _format_phone(whatsapp: str) -> str:
    """Normalise to E.164 without '+' — Evolution API expects '5511999990000'."""
    digits = "".join(c for c in whatsapp if c.isdigit())
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


def send_whatsapp(db: Session, to_whatsapp: str, message: str) -> bool:
    cfg = _get_client_config(db)
    if not cfg["url"] or not cfg["key"] or not cfg["instance"]:
        logger.warning("Evolution API não configurada — mensagem não enviada.")
        return False

    phone = _format_phone(to_whatsapp)
    url = f"{cfg['url'].rstrip('/')}/message/sendText/{cfg['instance']}"
    headers = {"apikey": cfg["key"], "Content-Type": "application/json"}
    payload = {
        "number": phone,
        "text": message,
    }
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info("WhatsApp enviado para %s", phone)
        return True
    except Exception as exc:
        logger.error("Erro ao enviar WhatsApp para %s: %s", phone, exc)
        return False
