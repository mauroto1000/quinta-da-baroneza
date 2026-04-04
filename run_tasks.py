"""
Scheduled task para o PythonAnywhere.
Configure na aba Tasks para rodar a cada hora (plano gratuito) ou cada minuto (pago).

Comando:
  /home/ranking2025/quinta-da-baronesa/venv/bin/python /home/ranking2025/quinta-da-baronesa/run_tasks.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from app.services.tasks import check_expired_steps

check_expired_steps()
