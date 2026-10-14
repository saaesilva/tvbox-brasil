#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 TutuTV Box Brasil - Versão Aprimorada para TV Box e PC
 Player Moderno de IPTV com Foco em Canais Abertos do Brasil, Alta Estabilidade,
 Resiliência de Rede, Picture-in-Picture (PiP), Auto-Healing e Telemetria em Tempo Real.
=============================================================================
"""

import os
import sys
import re
import json
import shutil
import subprocess
import unicodedata
import time
import threading
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import requests

try:
    import psutil
except ImportError:
    psutil = None

# Se executado em Python 32-bit no Windows enquanto o VLC for 64-bit,
# relança automaticamente com o inicializador 64-bit para evitar conflitos de DLL.
if sys.platform == "win32" and sys.maxsize <= 2**32:
    py_launcher = shutil.which("py")
    if py_launcher:
        try:
            ret = subprocess.call([py_launcher, "-3-64"] + sys.argv)
            sys.exit(ret)
        except Exception:
            pass

# Localização Automática da LibVLC no Windows
if sys.platform == "win32":
    vlc_paths = [
        r"C:\Program Files\VideoLAN\VLC",
        r"C:\Program Files (x86)\VideoLAN\VLC",
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "VideoLAN", "VLC"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "VideoLAN", "VLC")
    ]
    for path in vlc_paths:
        if os.path.exists(path) and os.path.exists(os.path.join(path, "libvlc.dll")):
            try:
                os.add_dll_directory(path)
                break
            except Exception:
                pass

try:
    import vlc
except ImportError:
    vlc = None

import PyQt6.QtCore as QtCore
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QComboBox,
    QListWidgetItem,
    QLabel,
    QPushButton,
    QFrame,
    QStackedWidget,
    QSlider,
    QProgressBar,
    QGraphicsOpacityEffect,
    QMessageBox,
    QInputDialog,
    QDialog,
    QScrollArea,
    QGroupBox,
    QCheckBox
)

from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings

# =============================================================================
# CONSTANTES E SISTEMA DE LOGGING ESTRUTURADO COM ROTAÇÃO E BUFFER EM MEMÓRIA
# =============================================================================
CONFIG_FILE = "config_iptv.json"
CACHE_FILE = "channels_cache.json"
CACHE_TTL_SECONDS = 86400  # 24 horas (Time-To-Live)
LOG_FILE = "app.log"
LOG_FORMAT = "[%(asctime)s] [%(levelname)-7s] [%(threadName)s] [%(funcName)s:%(lineno)d] %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


class InMemoryLogHandler(logging.Handler):
    """Armazena os últimos registros de log em memória para consulta pelo Painel de Diagnóstico (F12)."""
    def __init__(self, max_records=300):
        super().__init__()
        self.records = deque(maxlen=max_records)
        self.lock = threading.Lock()

    def emit(self, record):
        try:
            msg = self.format(record)
            with self.lock:
                self.records.append({
                    'timestamp': record.created,
                    'time_str': datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                    'level': record.levelname,
                    'module': record.module,
                    'message': record.getMessage(),
                    'formatted': msg
                })
        except Exception:
            self.handleError(record)

    def get_records(self):
        with self.lock:
            return list(self.records)

    def clear(self):
        with self.lock:
            self.records.clear()


logger = logging.getLogger("TVBox")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    # Rotação de logs em arquivo físico: até 5MB por arquivo, 3 cópias de backup
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Saída para terminal / console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # Buffer em memória para o painel de diagnóstico
    in_memory_log_handler = InMemoryLogHandler(max_records=300)
    in_memory_log_handler.setLevel(logging.DEBUG)
    in_memory_log_handler.setFormatter(file_formatter)
    logger.addHandler(in_memory_log_handler)
else:
    in_memory_log_handler = next((h for h in logger.handlers if isinstance(h, InMemoryLogHandler)), None)
    if not in_memory_log_handler:
        in_memory_log_handler = InMemoryLogHandler(max_records=300)
        in_memory_log_handler.setLevel(logging.DEBUG)
        in_memory_log_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
        logger.addHandler(in_memory_log_handler)


# =============================================================================
# GERENCIAMENTO DE CACHE LOCAL M3U COM TTL (TIME-TO-LIVE)
# =============================================================================
def load_channels_cache(cache_path=CACHE_FILE, ttl=CACHE_TTL_SECONDS):
    """
    Carrega a lista de canais e categorias do cache local.
    Retorna: (channels: list, categories: set, is_fresh: bool, age_hours: float)
    Permite inicialização offline instantânea se o cache tiver menos de 24 horas.
    """
    if not os.path.exists(cache_path):
        return [], set(), False, -1.0

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cache_time = float(data.get("timestamp", 0))
        age_seconds = time.time() - cache_time
        age_hours = age_seconds / 3600.0
        is_fresh = age_seconds < ttl

        channels = data.get("channels", [])
        categories = set(data.get("categories", []))

        logger.info(
            f"Cache M3U lido com sucesso: {len(channels)} canais, {len(categories)} categorias. "
            f"Idade do cache: {age_hours:.1f}h (TTL {'válido (<24h)' if is_fresh else 'expirado (>24h)'})."
        )
        return channels, categories, is_fresh, age_hours
    except Exception as e:
        logger.error(f"Erro ao ler cache M3U local '{cache_path}': {e}", exc_info=True)
        return [], set(), False, -1.0


def save_channels_cache(channels, categories, url, cache_path=CACHE_FILE):
    """Salva a lista M3U descarregada num ficheiro local com carimbo de data/hora (TTL de 24h)."""
    try:
        payload = {
            "timestamp": time.time(),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "url": url,
            "channels_count": len(channels),
            "categories": sorted(list(categories)),
            "channels": channels
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"Cache local M3U gravado em '{cache_path}' ({len(channels)} canais salvos).")
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar cache M3U em '{cache_path}': {e}", exc_info=True)
        return False

CANAIS_ABERTOS_BRASIL = [
    {
        'name': 'SBT Nacional (Ao Vivo)',
        'url': 'https://cdn.live.br1.jmvstream.com/w/LVW-10801/LVW10801_Xvg4R0u57n/playlist.m3u8',
        'fallback_urls': ['https://cdn.jmvstream.com/w/LVW-10801/LVW10801_Xvg4R0u57n/playlist.m3u8'],
        'group': 'TV Aberta Brasil',
        'badge': '1080p • AO VIVO'
    },
    {
        'name': 'Record News (Ao Vivo)',
        'url': 'https://rnw-rn.otteravision.com/rnw/rn/rnw_rn.m3u8',
        'fallback_urls': ['http://45.162.64.114/RECORD_NEWS/index.m3u8'],
        'group': 'TV Aberta Brasil',
        'badge': '720p • NOTÍCIAS'
    },
    {
        'name': 'TV Cultura (Ao Vivo)',
        'url': 'https://player-tvcultura.stream.uol.com.br/live/tvcultura.m3u8',
        'fallback_urls': ['http://45.162.64.114/TV_CULTURA/index.m3u8'],
        'group': 'TV Aberta Brasil',
        'badge': 'HD • EDUCATIVA'
    },
    {
        'name': 'TV Brasil (Ao Vivo)',
        'url': 'http://45.162.64.114/TV_BRASIL/index.m3u8',
        'fallback_urls': ['http://45.177.114.115/TV_BRASIL_2/index.m3u8'],
        'group': 'TV Aberta Brasil',
        'badge': '720p • PÚBLICA'
    },
    {
        'name': 'CNN Brasil (Ao Vivo)',
        'url': 'https://d25usgadhphvwi.cloudfront.net/hls/main.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '1080p • NOTÍCIAS'
    },
    {
        'name': 'TV Câmara (Ao Vivo)',
        'url': 'https://stream3.camara.gov.br/tv1/manifest.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '1080p • OFICIAL'
    },
    {
        'name': 'TV Senado (Ao Vivo)',
        'url': 'http://45.162.64.114/TV_SENADO/index.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '720p • OFICIAL'
    },
    {
        'name': 'TV Justiça (Ao Vivo)',
        'url': 'http://45.162.64.114/TV_JUSTICA/index.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '720p • INSTITUCIONAL'
    },
    {
        'name': 'TV Gazeta SP (Ao Vivo)',
        'url': 'http://45.162.64.114/GAZETA/index.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '720p • AO VIVO'
    },
    {
        'name': 'RedeTV! (Ao Vivo)',
        'url': 'https://tv01.zas.media:1936/redetvparana/redetvparana/playlist.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': 'HD • AO VIVO'
    },
    {
        'name': 'Rede Brasil (Ao Vivo)',
        'url': 'https://video09.logicahost.com.br/redebrasiloficial/redebrasiloficial/playlist.m3u8',
        'fallback_urls': ['https://redebrasil.nuvemplay.live/hls/stream.m3u8'],
        'group': 'TV Aberta Brasil',
        'badge': '1080p • AO VIVO'
    },
    {
        'name': 'Canal Futura (Ao Vivo)',
        'url': 'http://168.197.104.22/FUTURA/index.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '720p • EDUCATIVA'
    },
    {
        'name': 'Canal Gov (EBC)',
        'url': 'http://45.177.114.115/TV_BRASIL_2/index.m3u8',
        'fallback_urls': ['http://45.162.64.114/TV_BRASIL/index.m3u8'],
        'group': 'TV Aberta Brasil',
        'badge': '720p • INFORMATIVO'
    },
    {
        'name': 'Jovem Pan News (Ao Vivo)',
        'url': 'http://170.83.49.66:8083/JOVEMPANNEWSHD/index.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '720p • NOTÍCIAS'
    },
    {
        'name': 'Band Sports (Ao Vivo)',
        'url': 'http://45.162.64.114/BAND_SPORTS/index.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '720p • ESPORTES'
    },
    {
        'name': 'Arte 1 (Ao Vivo)',
        'url': 'http://45.162.64.114/ARTE1/index.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '720p • CULTURA'
    },
    {
        'name': 'AgroMais (Ao Vivo)',
        'url': 'http://45.162.64.114/AGROMAIS/index.m3u8',
        'fallback_urls': [],
        'group': 'TV Aberta Brasil',
        'badge': '720p • AGRO'
    },
    {
        'name': 'SBT Interior SP (Ao Vivo)',
        'url': 'https://cdn.jmvstream.com/w/LVW-10801/LVW10801_Xvg4R0u57n/playlist.m3u8',
        'fallback_urls': ['https://cdn.live.br1.jmvstream.com/w/LVW-10801/LVW10801_Xvg4R0u57n/playlist.m3u8'],
        'group': 'TV Aberta Brasil',
        'badge': '720p • REGIONAL'
    }
]

# DICIONÁRIO COMPLETO DE TRADUÇÃO DE CATEGORIAS PARA PT-BR
CATEGORY_TRANSLATIONS = {
    "Animation": "Infantil / Animação",
    "Kids": "Infantil",
    "Children": "Infantil",
    "Movies": "Filmes",
    "Movie": "Filmes",
    "Film": "Filmes",
    "Series": "Séries",
    "News": "Notícias",
    "Sports": "Esportes",
    "Sport": "Esportes",
    "Entertainment": "Entretenimento",
    "Music": "Música",
    "Documentaries": "Documentários",
    "Documentary": "Documentários",
    "General": "Geral",
    "Comedy": "Comédia",
    "Classic": "Clássicos",
    "Business": "Negócios / Finanças",
    "Auto": "Automobilismo",
    "Religious": "Religioso",
    "Religion": "Religioso",
    "Culture": "Cultura",
    "Education": "Educação",
    "Educational": "Educação",
    "Lifestyle": "Estilo de Vida",
    "Science": "Ciência / Tecnologia",
    "Travel": "Viagens",
    "Weather": "Clima / Tempo",
    "Cooking": "Culinária",
    "Family": "Família",
    "Outdoor": "Natureza / Aventura",
    "Legislative": "Legislativo",
    "Public": "TV Pública",
    "Shop": "Compras / Variedades",
    "Shopping": "Compras / Variedades",
    "Undefined": "Outros"
}

def remove_accents(text: str) -> str:
    """Remove acentos e normaliza caracteres para pesquisa rápida e sem falhas."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower()


# =============================================================================
# MOTOR DE GUIA DE PROGRAMAÇÃO (EPG - ELETRONIC PROGRAM GUIDE)
# =============================================================================
class EPGManager:
    """Gerenciador Inteligente de Guia de Programação (EPG) para Canais Brasileiros."""

    CHANNEL_GRIDS = {
        'SBT': [
            ('01:30', '06:00', 'SBT News na Madrugada', 'Jornalismo 24 horas com as principais notícias do Brasil e do mundo.'),
            ('06:00', '09:30', 'Primeiro Impacto', 'As primeiras notícias da manhã, trânsito, previsão do tempo e utilidade pública.'),
            ('09:30', '11:30', 'Chega Mais', 'Revista eletrônica com variedades, culinária, comportamento e informação leve.'),
            ('11:30', '13:30', 'SBT Notícias / Edição Regional', 'Informação local, notícias policiais e reportagens exclusivas ao vivo.'),
            ('13:30', '15:30', 'Novelas da Tarde', 'Grandes sucessos da dramaturgia nacional e internacional.'),
            ('15:30', '17:30', 'Fofocalizando', 'O mundo dos famosos, bastidores da TV, fofocas e entrevistas quentes.'),
            ('17:30', '19:45', 'Tá na Hora', 'Jornalismo comunitário e dinâmico com os fatos marcantes do final da tarde.'),
            ('19:45', '20:30', 'SBT Brasil', 'O principal telejornal da emissora com os temas mais importantes do dia.'),
            ('20:30', '21:30', 'A Infância de Romeu e Julieta', 'Telenovela infanto-juvenil repleta de aventuras e música para toda a família.'),
            ('21:30', '22:30', 'Programa do Ratinho', 'Auditório ao vivo, atrações musicais, quadros cômicos e reportagens especiais.'),
            ('22:30', '00:00', 'The Noite com Danilo Gentili', 'Talk show com entrevistas descontraídas, humor ácido e convidados especiais.'),
            ('00:00', '01:30', 'Operação Mesquita & PodNight', 'Curiosidades da noite, entrevistas e podcasts populares na TV aberta.')
        ],
        'Record News': [
            ('00:00', '06:00', 'Record News Madrugada', 'Boletins 24h e as notícias mais importantes da madrugada.'),
            ('06:00', '08:00', 'Hora News - Manhã', 'Giro completo pelos primeiros acontecimentos do dia no Brasil e no exterior.'),
            ('08:00', '09:30', 'Boletim R7 & Economia', 'Cotações do mercado, agronegócio e as manchetes do portal R7.'),
            ('09:30', '12:00', 'Conexão Record News', 'Análise política, entrevistas ao vivo e os principais debates nacionais.'),
            ('12:00', '14:00', 'Record News Paulista', 'Notícias das capitais, trânsito ao vivo e cobertura dos fatos regionais.'),
            ('14:00', '16:30', 'Mundo Record News', 'Panorama internacional, geopolítica e cobertura com correspondentes.'),
            ('16:30', '18:30', 'Link Record News', 'Transmissões em tempo real, links ao vivo e notícias de última hora.'),
            ('18:30', '20:30', 'Hora News Especial', 'Resumo aprofundado dos principais temas do final da tarde.'),
            ('20:30', '21:45', 'Jornal da Record News', 'O principal telejornal da casa com análises precisas dos fatos.'),
            ('21:45', '23:30', 'Esporte Record News & Debates', 'Giro pelos gols da rodada, campeonatos e entrevistas com atletas.'),
            ('23:30', '00:00', 'Record News Investigação', 'Grandes reportagens e matérias investigativas exclusivas.')
        ],
        'TV Cultura': [
            ('00:00', '06:00', 'Doc Cultura Madrugada', 'Documentários internacionais e produções culturais premiadas.'),
            ('06:00', '07:30', 'Brasil Rural & Missa de Aparecida', 'O despertar do trabalhador do campo e espiritualidade.'),
            ('07:30', '09:00', 'Cocoricó Clássico', 'As aventuras de Júlio e sua turma na fazenda mais famosa do Brasil.'),
            ('09:00', '11:30', 'Quintal da Cultura (Especial)', 'Brincadeiras, contação de histórias e desenhos educativos.'),
            ('11:30', '12:00', 'JC Debate', 'Debates aprofundados sobre temas sociais e cidadania.'),
            ('12:00', '13:00', 'Jornal da Tarde', 'Informação de qualidade com foco em São Paulo e no Brasil.'),
            ('13:00', '15:30', 'Quintal da Cultura - Tarde', 'Doroteia, Ludovico e Osório com muita diversão educativa.'),
            ('15:30', '17:00', 'Planeta Terra Documentários', 'A natureza fascinante e a vida selvagem ao redor do globo.'),
            ('17:00', '18:30', 'Mundo em Foco & Inovação', 'Tecnologia, ciência e o futuro da sociedade moderna.'),
            ('18:30', '19:30', 'Metrópolis', 'O mais tradicional programa de arte, cinema e cultura pop da TV.'),
            ('19:30', '20:30', 'Jornal da Cultura Primeira Edição', 'Noticiário dinâmico com os fatos relevantes do dia.'),
            ('20:30', '21:15', 'Jornal da Cultura', 'Comentaristas consagrados analisam os temas mais quentes do país.'),
            ('21:15', '22:30', 'Roda Viva', 'O maior programa de entrevistas do Brasil recebendo personalidades de destaque.'),
            ('22:30', '00:00', 'Showlivre & MPB Clássicos', 'Shows ao vivo com os grandes ícones da música brasileira.')
        ],
        'TV Brasil': [
            ('00:00', '06:00', 'Madrugada TV Brasil', 'Acervo de documentários, cinema brasileiro e memória nacional.'),
            ('06:00', '08:00', 'Brasil em Dia Manhã', 'Prestação de contas, serviços públicos e cidadania.'),
            ('08:00', '10:00', 'Repórter Brasil Manhã', 'Notícias ao vivo de todas as regiões do Brasil direto de Brasília.'),
            ('10:00', '12:00', 'TV Brasil Animada', 'Faixa infantil com desenhos nacionais de sucesso e animações educativas.'),
            ('12:00', '13:30', 'Repórter Brasil Tarde', 'Cobertura completa do expediente público e notícias do país.'),
            ('13:30', '15:00', 'Sem Censura', 'O clássico programa de entrevistas e debates culturais.'),
            ('15:00', '17:30', 'Natureza Viva & Documentários EBC', 'Belezas do cerrado, amazônia e fauna brasileira.'),
            ('17:30', '19:00', 'Caminhos da Reportagem', 'Grandes reportagens em profundidade e jornalismo investigativo premiado.'),
            ('19:00', '20:00', 'Repórter Brasil Noite', 'O resumo do dia com as principais manchetes de interesse público.'),
            ('20:00', '21:00', 'A Voz do Brasil na TV', 'Transmissão oficial do noticiário dos poderes da República.'),
            ('21:00', '22:30', 'Estação Cinema Brasileiro', 'Exibição de clássicos e produções contemporâneas do cinema nacional.'),
            ('22:30', '00:00', 'Samba na Gamboa & Sons do Brasil', 'Música autêntica com Diogo Nogueira e convidados especiais.')
        ],
        'CNN Brasil': [
            ('00:00', '06:00', 'CNN Madrugada 24h', 'Plantão contínuo e reprises dos principais debates do dia.'),
            ('06:00', '09:00', 'CNN Novo Dia', 'O panorama matinal com as movimentações dos bastidores de Brasília.'),
            ('09:00', '12:00', 'Live CNN Brasil', 'Jornalismo ágil com entradas ao vivo de repórteres de todo o país.'),
            ('12:00', '15:00', 'O Grande Debate / Visão CNN', 'Debates de pontos de vista divergentes sobre os temas polêmicos do momento.'),
            ('15:00', '18:00', 'CNN 360 Graus', 'Cobertura política intensa com análises de especialistas consagrados.'),
            ('18:00', '20:00', 'CNN Arena Política', 'A temperatura do poder legislativo, executivo e judiciário.'),
            ('20:00', '22:00', 'CNN Prime Time', 'O horário nobre das notícias com análises aprofundadas.'),
            ('22:00', '23:30', 'Jornal da CNN', 'A síntese factual completa dos acontecimentos mais impactantes.'),
            ('23:30', '00:00', 'WW com William Waack', 'Análise geopolítica, economia internacional e grandes decisões.')
        ]
    }

    GENERIC_CATEGORIES = {
        'Notícias': [
            ('00:00', '06:00', 'Plantão Notícias Madrugada', 'Giro contínuo das manchetes e fatos internacionais.'),
            ('06:00', '09:00', 'Jornal da Manhã Ao Vivo', 'Primeiras notícias, trânsito, economia e destaques.'),
            ('09:00', '12:00', 'Conexão Notícias', 'Entrevistas, debates e repórteres ao vivo.'),
            ('12:00', '14:00', 'Telejornal do Meio-Dia', 'Balanço da manhã e principais fatos em andamento.'),
            ('14:00', '17:00', 'Giro em Pauta', 'Economia, mercado financeiro e política.'),
            ('17:00', '19:30', 'Edição do Fim de Tarde', 'Os temas que marcaram o dia no país.'),
            ('19:30', '21:00', 'Principal Telejornal', 'As reportagens mais relevantes e análises.'),
            ('21:00', '23:00', 'Mesa de Debates Políticos', 'Comentaristas e analistas em discussão aberta.'),
            ('23:00', '00:00', 'Jornal da Noite', 'Síntese das 24 horas e projeções para amanhã.')
        ],
        'Esportes': [
            ('00:00', '06:00', 'VT Clássicos & Memória do Futebol', 'Jogos memoráveis e momentos históricos do esporte.'),
            ('06:00', '09:00', 'Giro dos Campeonatos', 'Resultados da rodada, bastidores dos clubes e gols.'),
            ('09:00', '12:00', 'Primeiro Tempo Debate', 'Comentaristas analisam escalações e táticas.'),
            ('12:00', '14:30', 'Os Donos da Bola Ao Vivo', 'Muita resenha, polêmica e humor sobre futebol.'),
            ('14:30', '17:30', 'Central do Esporte & Automobilismo', 'Fórmula 1, basquete, lutas e esportes radicais.'),
            ('17:30', '20:30', 'Esporte Total & Entrevistas', 'Exclusivas com atletas e técnicos consagrados.'),
            ('20:30', '22:30', 'Noite dos Craques Ao Vivo', 'Análise aprofundada dos jogos da rodada.'),
            ('22:30', '00:00', 'Goleada & Mesa Redonda', 'O melhor do encerramento da jornada esportiva.')
        ],
        'Educativa': [
            ('00:00', '06:00', 'Madrugada Educativa', 'Aulas, cursos livres e documentários históricos.'),
            ('06:00', '08:30', 'Telecurso & Ensino Médio', 'Aulas dinâmicas de matemática, história e ciências.'),
            ('08:30', '12:00', 'Mundo da Descoberta Infantil', 'Programas lúdicos para formação e criatividade.'),
            ('12:00', '14:00', 'Ciência em Casa', 'Experimentos práticos e inovações da ciência.'),
            ('14:00', '17:00', 'Natureza & Meio Ambiente', 'Preservação da fauna e sustentabilidade do planeta.'),
            ('17:00', '20:00', 'Histórias do Brasil & Cidadania', 'A evolução histórica e a riqueza cultural do país.'),
            ('20:00', '22:30', 'Grandes Debates Universitários', 'Pesquisadores abordam os desafios contemporâneos.'),
            ('22:30', '00:00', 'Cinema Educativo & Arte', 'Exibição comentada de curtas e filmes conceituados.')
        ],
        'Geral': [
            ('00:00', '06:00', 'Sessão Madrugada', 'Filmes, séries e documentários clássicos.'),
            ('06:00', '09:00', 'Manhã em Revista', 'Informações, previsão do tempo e utilidade pública.'),
            ('09:00', '12:00', 'Variedades & Bem-Estar', 'Saúde, beleza, jardinagem e qualidade de vida.'),
            ('12:00', '14:00', 'Jornal Regional', 'Notícias ao vivo da sua comunidade.'),
            ('14:00', '16:00', 'Cozinha & Sabores', 'Receitas práticas e segredos dos chefs de cozinha.'),
            ('16:00', '18:30', 'Tarde de Novelas', 'Dramas emocionantes e romances consagrados.'),
            ('18:30', '20:00', 'Telejornal da Cidade', 'As notícias mais importantes do fim do dia.'),
            ('20:00', '22:30', 'Super Sessão de Cinema', 'Os maiores sucessos da telona na TV aberta.'),
            ('22:30', '00:00', 'Programa de Entrevistas', 'Conversas descontraídas com grandes personalidades.')
        ]
    }

    @classmethod
    def get_schedule_for_channel(cls, channel_name: str, category: str = "Geral"):
        name_lower = channel_name.lower()
        if 'sbt' in name_lower:
            return cls.CHANNEL_GRIDS['SBT']
        elif 'record' in name_lower:
            return cls.CHANNEL_GRIDS['Record News']
        elif 'cultura' in name_lower:
            return cls.CHANNEL_GRIDS['TV Cultura']
        elif 'tv brasil' in name_lower or 'gov' in name_lower:
            return cls.CHANNEL_GRIDS['TV Brasil']
        elif 'cnn' in name_lower:
            return cls.CHANNEL_GRIDS['CNN Brasil']
        
        cat_lower = category.lower()
        if 'esporte' in cat_lower or 'sports' in cat_lower or 'band sports' in name_lower:
            return cls.GENERIC_CATEGORIES['Esportes']
        elif 'educat' in cat_lower or 'cultur' in cat_lower or 'futura' in name_lower:
            return cls.GENERIC_CATEGORIES['Educativa']
        elif 'not' in cat_lower or 'news' in cat_lower or 'jovem pan' in name_lower or 'gazeta' in name_lower or 'senado' in name_lower or 'camara' in name_lower or 'justica' in name_lower:
            return cls.GENERIC_CATEGORIES['Notícias']
        else:
            return cls.GENERIC_CATEGORIES['Geral']

    @classmethod
    def get_current_and_upcoming(cls, channel_name: str, category: str = "Geral"):
        schedule = cls.get_schedule_for_channel(channel_name, category)
        now = datetime.now()
        base_date = now.date()

        parsed_slots = []
        for start_s, end_s, title, desc in schedule:
            sh, sm = map(int, start_s.split(':'))
            eh, em = map(int, end_s.split(':'))

            st = datetime(base_date.year, base_date.month, base_date.day, sh, sm)
            et = datetime(base_date.year, base_date.month, base_date.day, eh, em)

            if et <= st:  # Transpõe meia-noite
                et += timedelta(days=1)

            parsed_slots.append((st, et, title, desc, start_s, end_s))

        current_idx = 0
        for idx, (st, et, title, desc, start_s, end_s) in enumerate(parsed_slots):
            if st <= now < et:
                current_idx = idx
                break
            st_prev = st - timedelta(days=1)
            et_prev = et - timedelta(days=1)
            if st_prev <= now < et_prev:
                current_idx = idx
                break

        curr_st, curr_et, curr_title, curr_desc, start_str, end_str = parsed_slots[current_idx]

        total_seconds = max(1, (curr_et - curr_st).total_seconds())
        elapsed_seconds = max(0, (now - curr_st).total_seconds())
        progress_pct = min(100, max(0, int((elapsed_seconds / total_seconds) * 100)))

        remaining_seconds = max(0, (curr_et - now).total_seconds())
        remaining_minutes = int(remaining_seconds // 60)
        if remaining_minutes < 1:
            remaining_str = "Terminando agora"
        elif remaining_minutes < 60:
            remaining_str = f"Faltam {remaining_minutes} min"
        else:
            hours = remaining_minutes // 60
            mins = remaining_minutes % 60
            remaining_str = f"Faltam {hours}h {mins}min"

        current_program_info = {
            'title': curr_title,
            'desc': curr_desc,
            'start': start_str,
            'end': end_str,
            'progress': progress_pct,
            'remaining': remaining_str,
            'time_range': f"{start_str} - {end_str}"
        }

        upcoming = []
        for i in range(1, 4):
            nxt_idx = (current_idx + i) % len(parsed_slots)
            _, _, n_title, n_desc, n_start, n_end = parsed_slots[nxt_idx]
            upcoming.append({
                'title': n_title,
                'desc': n_desc,
                'start': n_start,
                'end': n_end,
                'time_range': f"{n_start} - {n_end}"
            })

        return current_program_info, upcoming, schedule


# =============================================================================
# JANELA DO GUIA COMPLETO DE PROGRAMAÇÃO (TV GUIDE / GRADE EPG)
# =============================================================================
class TVGuideDialog(QDialog):
    """Guia Visual de Programação de TV de tela cheia estilo Smart TV."""

    def __init__(self, channels, current_index, on_select_channel, parent=None):
        super().__init__(parent)
        self.channels = channels
        self.selected_index = current_index
        self.on_select_channel = on_select_channel

        self.setWindowTitle("Guia de Programação de TV (EPG)")
        self.setMinimumSize(950, 600)
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0f172a, stop:1 #020617);
                color: #f1f5f9;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QLabel { color: #f8fafc; }
            QListWidget {
                background-color: #0b0f19;
                border: 1px solid #1e293b;
                border-radius: 12px;
                outline: 0;
            }
            QListWidget::item {
                background-color: #111827;
                border-radius: 8px;
                margin: 4px;
                padding: 12px;
                font-size: 14px;
                font-weight: 600;
                border: 1px solid #1f2937;
            }
            QListWidget::item:hover {
                background-color: #1e293b;
                border-color: #3b82f6;
            }
            QListWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #1d4ed8);
                color: #ffffff;
                font-weight: bold;
                border: 1px solid #60a5fa;
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            QPushButton.tune-btn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #1d4ed8);
                color: #ffffff;
                font-weight: bold;
                font-size: 15px;
                border-radius: 10px;
                padding: 12px 24px;
                border: 1px solid #60a5fa;
            }
            QPushButton.tune-btn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #2563eb);
            }
            QPushButton.close-btn {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: 600;
                font-size: 14px;
                border-radius: 10px;
                padding: 10px 20px;
                border: 1px solid #334155;
            }
            QPushButton.close-btn:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Cabeçalho do Guia
        header_layout = QHBoxLayout()
        title_lbl = QLabel("📅 GUIA DE PROGRAMAÇÃO DA TV")
        title_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #38bdf8; letter-spacing: 1px;")

        now_str = datetime.now().strftime("%H:%M  •  %d de %B de %Y")
        self.clock_lbl = QLabel(f"🕒 {now_str}")
        self.clock_lbl.setFont(QFont("Segoe UI", 12))
        self.clock_lbl.setStyleSheet("color: #94a3b8;")

        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        header_layout.addWidget(self.clock_lbl)
        layout.addLayout(header_layout)

        # Corpo: Duas Colunas (Lista de Canais à esquerda e Grade de Horários à direita)
        body_layout = QHBoxLayout()
        body_layout.setSpacing(18)

        # Coluna 1: Canais
        left_box = QVBoxLayout()
        ch_list_title = QLabel("CANAIS DISPONÍVEIS:")
        ch_list_title.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: bold;")
        left_box.addWidget(ch_list_title)

        self.ch_list = QListWidget()
        self.ch_list.setFixedWidth(320)
        for idx, ch in enumerate(self.channels):
            item = QListWidgetItem(f"{idx+1:02d}. 📺 {ch['name']}")
            self.ch_list.addItem(item)
        self.ch_list.currentRowChanged.connect(self.on_channel_clicked)
        left_box.addWidget(self.ch_list)
        body_layout.addLayout(left_box)

        # Coluna 2: Programação Completa do Canal Selecionado
        right_box = QVBoxLayout()
        self.selected_ch_title = QLabel("Selecione um canal")
        self.selected_ch_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.selected_ch_title.setStyleSheet("color: #ffffff;")
        right_box.addWidget(self.selected_ch_title)

        self.schedule_scroll = QScrollArea()
        self.schedule_scroll.setWidgetResizable(True)
        self.schedule_content = QWidget()
        self.schedule_layout = QVBoxLayout(self.schedule_content)
        self.schedule_layout.setSpacing(10)
        self.schedule_layout.addStretch()
        self.schedule_scroll.setWidget(self.schedule_content)
        right_box.addWidget(self.schedule_scroll)
        body_layout.addLayout(right_box, stretch=1)

        layout.addLayout(body_layout)

        # Rodapé com Botão de Ação
        footer_layout = QHBoxLayout()
        tip_lbl = QLabel("Dica: Use as setas do teclado/controle remoto para navegar e pressione [Enter] para assistir.")
        tip_lbl.setStyleSheet("color: #64748b; font-size: 12px;")

        self.btn_tune = QPushButton("▶️ Assistir a Este Canal")
        self.btn_tune.setProperty("class", "tune-btn")
        self.btn_tune.clicked.connect(self.tune_selected)

        btn_close = QPushButton("Fechar Guia [Esc]")
        btn_close.setProperty("class", "close-btn")
        btn_close.clicked.connect(self.reject)

        footer_layout.addWidget(tip_lbl)
        footer_layout.addStretch()
        footer_layout.addWidget(self.btn_tune)
        footer_layout.addWidget(btn_close)
        layout.addLayout(footer_layout)

        if 0 <= self.selected_index < len(self.channels):
            self.ch_list.setCurrentRow(self.selected_index)

    def on_channel_clicked(self, row):
        if 0 <= row < len(self.channels):
            self.selected_index = row
            channel = self.channels[row]
            self.selected_ch_title.setText(f"📺 {row+1:02d}. {channel['name']} - Programação do Dia")

            # Limpa itens anteriores da grade
            while self.schedule_layout.count() > 1:
                child = self.schedule_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            curr_info, upcoming_info, full_grid = EPGManager.get_current_and_upcoming(
                channel['name'],
                channel.get('group', 'Geral')
            )

            for start_s, end_s, title, desc in full_grid:
                is_current = (title == curr_info['title'])
                card = QFrame()
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(14, 10, 14, 10)
                card_layout.setSpacing(4)

                if is_current:
                    card.setStyleSheet("""
                        QFrame {
                            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(37, 99, 235, 0.35), stop:1 rgba(30, 41, 59, 0.7));
                            border: 2px solid #3b82f6;
                            border-radius: 10px;
                        }
                    """)
                    badge = QLabel(f"🔴 NO AR AGORA  •  {start_s} às {end_s}")
                    badge.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 12px;")
                    card_layout.addWidget(badge)
                else:
                    card.setStyleSheet("""
                        QFrame {
                            background-color: #0f172a;
                            border: 1px solid #1e293b;
                            border-radius: 8px;
                        }
                    """)
                    time_lbl = QLabel(f"🕒 {start_s} às {end_s}")
                    time_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: bold;")
                    card_layout.addWidget(time_lbl)

                t_lbl = QLabel(title)
                t_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
                t_lbl.setStyleSheet("color: #ffffff;")
                card_layout.addWidget(t_lbl)

                d_lbl = QLabel(desc)
                d_lbl.setWordWrap(True)
                d_lbl.setStyleSheet("color: #cbd5e1; font-size: 12px;")
                card_layout.addWidget(d_lbl)

                if is_current:
                    pbar = QProgressBar()
                    pbar.setRange(0, 100)
                    pbar.setValue(curr_info['progress'])
                    pbar.setTextVisible(False)
                    pbar.setFixedHeight(6)
                    pbar.setStyleSheet("""
                        QProgressBar { background-color: #1e293b; border-radius: 3px; }
                        QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38bdf8, stop:1 #2563eb); border-radius: 3px; }
                    """)
                    card_layout.addWidget(pbar)

                    rem_lbl = QLabel(f"⏱️ Progresso: {curr_info['progress']}%  •  {curr_info['remaining']}")
                    rem_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
                    card_layout.addWidget(rem_lbl)

                self.schedule_layout.insertWidget(self.schedule_layout.count() - 1, card)

    def tune_selected(self):
        row = self.ch_list.currentRow()
        if 0 <= row < len(self.channels):
            self.on_select_channel(row)
            self.accept()


# =============================================================================
# DIÁLOGO DE CONFIGURAÇÕES DE ÁUDIO E VÍDEO (OTIMIZADOR SMART TV)
# =============================================================================
class AVSettingsDialog(QDialog):
    """
    Diálogo para Nivelamento de Volume de Canais Baixos e Otimização/Upscaling de Vídeo.
    Garante que todos os canais tenham volume homogêneo e imagem nítida com cores vivas.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Otimizador de Áudio e Vídeo - Padrão Smart TV")
        self.setFixedSize(680, 600)
        self.setStyleSheet("""
            QDialog {
                background-color: #0b0f19;
                color: #f1f5f9;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }
            QGroupBox {
                border: 1px solid #334155;
                border-radius: 10px;
                margin-top: 14px;
                padding: 14px;
                font-size: 13px;
                font-weight: bold;
                color: #38bdf8;
                background-color: #111827;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
            }
            QLabel {
                color: #cbd5e1;
                font-size: 12px;
            }
            QComboBox {
                background-color: #1e293b;
                color: #ffffff;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 7px 12px;
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QCheckBox {
                color: #f1f5f9;
                font-size: 12px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #475569;
                background-color: #1e293b;
            }
            QCheckBox::indicator:checked {
                background-color: #38bdf8;
                border: 1px solid #38bdf8;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #1e293b;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #38bdf8;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 2px solid #38bdf8;
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
            QPushButton.save-btn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #2563eb);
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border-radius: 8px;
                padding: 10px 22px;
                border: none;
            }
            QPushButton.save-btn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38bdf8, stop:1 #3b82f6);
            }
            QPushButton.cancel-btn {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: 600;
                font-size: 13px;
                border-radius: 8px;
                padding: 10px 20px;
                border: 1px solid #334155;
            }
            QPushButton.cancel-btn:hover {
                background-color: #334155;
                color: #ffffff;
            }
            QPushButton.reset-btn {
                background-color: transparent;
                color: #38bdf8;
                font-size: 12px;
                text-decoration: underline;
                border: none;
                padding: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        # Cabeçalho
        head_layout = QHBoxLayout()
        title_lbl = QLabel("✨ CENTRAL DE QUALIDADE DE ÁUDIO & VÍDEO")
        title_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #38bdf8; letter-spacing: 0.5px;")
        head_layout.addWidget(title_lbl)
        head_layout.addStretch()
        layout.addLayout(head_layout)

        subtitle_lbl = QLabel("Otimização inteligente para canais com volume baixo e transmissões em baixa definição.")
        subtitle_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(subtitle_lbl)

        # -------------------------------------------------------------
        # SEÇÃO 1: EQUALIZAÇÃO E NIVELAMENTO DE ÁUDIO
        # -------------------------------------------------------------
        audio_group = QGroupBox("🔊 Equalização e Nivelamento de Volume")
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setSpacing(10)

        self.chk_normvol = QCheckBox("Ativar Nivelamento Automático de Volume (Equalizador / AGC)")
        self.chk_normvol.setChecked(getattr(parent, 'audio_normalizer_enabled', True))
        audio_layout.addWidget(self.chk_normvol)

        mode_row = QHBoxLayout()
        mode_lbl = QLabel("Perfil de Som:")
        mode_lbl.setFixedWidth(130)
        self.combo_audio_mode = QComboBox()
        self.combo_audio_mode.addItem("🔊 Nivelamento Inteligente (Equilibra canais baixos automaticamente)", "smart")
        self.combo_audio_mode.addItem("🎙️ Diálogos & Notícias Claras (Reforço Vocal)", "dialogue")
        self.combo_audio_mode.addItem("🎵 Padrão / Direto (Sem processamento)", "flat")

        current_a_mode = getattr(parent, 'audio_mode', 'smart')
        idx = self.combo_audio_mode.findData(current_a_mode)
        if idx >= 0:
            self.combo_audio_mode.setCurrentIndex(idx)

        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self.combo_audio_mode, stretch=1)
        audio_layout.addLayout(mode_row)

        preamp_row = QHBoxLayout()
        preamp_lbl = QLabel("Ganho Pré-Amp (Boost):")
        preamp_lbl.setFixedWidth(130)

        self.preamp_slider = QSlider(QtCore.Qt.Orientation.Horizontal)
        self.preamp_slider.setRange(0, 14)  # 0 a 14 dB
        current_preamp = int(getattr(parent, 'audio_preamp', 6.0))
        self.preamp_slider.setValue(current_preamp)

        self.preamp_val_lbl = QLabel(f"+{current_preamp}.0 dB (Elevação para canais silenciosos)")
        self.preamp_val_lbl.setStyleSheet("color: #38bdf8; font-weight: bold;")
        self.preamp_slider.valueChanged.connect(
            lambda v: self.preamp_val_lbl.setText(f"+{v}.0 dB (Elevação para canais silenciosos)" if v > 0 else "0.0 dB (Original)")
        )

        preamp_row.addWidget(preamp_lbl)
        preamp_row.addWidget(self.preamp_slider, stretch=1)
        preamp_row.addWidget(self.preamp_val_lbl)
        audio_layout.addLayout(preamp_row)

        tip_audio = QLabel("💡 Dica: O nivelador detecta transmissões baixas e ajusta o volume automaticamente sem estourar o som.")
        tip_audio.setStyleSheet("color: #64748b; font-size: 11px;")
        audio_layout.addWidget(tip_audio)

        layout.addWidget(audio_group)

        # -------------------------------------------------------------
        # SEÇÃO 2: OTIMIZAÇÃO E PROPORÇÃO DE VÍDEO SMART TV
        # -------------------------------------------------------------
        video_group = QGroupBox("📺 Otimização de Imagem & Proporção Smart TV")
        video_layout = QVBoxLayout(video_group)
        video_layout.setSpacing(10)

        vmode_row = QHBoxLayout()
        vmode_lbl = QLabel("Proporção / Formato:")
        vmode_lbl.setFixedWidth(130)
        self.combo_video_mode = QComboBox()
        self.combo_video_mode.addItem("✨ Widescreen 16:9 (Padrão TV Moderna)", "vivid")
        self.combo_video_mode.addItem("🎬 Automático / Original (Formato Nativo)", "cinema")
        self.combo_video_mode.addItem("📻 Clássico 4:3 (Transmissões Antigas)", "4:3")

        current_v_mode = getattr(parent, 'video_mode', 'vivid')
        vidx = self.combo_video_mode.findData(current_v_mode)
        if vidx >= 0:
            self.combo_video_mode.setCurrentIndex(vidx)

        vmode_row.addWidget(vmode_lbl)
        vmode_row.addWidget(self.combo_video_mode, stretch=1)
        video_layout.addLayout(vmode_row)

        self.chk_deinterlace = QCheckBox("Desentrelaçamento Inteligente Yadif 2x (Remove linhas horizontais e ativa 60 FPS)")
        self.chk_deinterlace.setChecked(getattr(parent, 'video_deinterlace_enabled', True))
        video_layout.addWidget(self.chk_deinterlace)

        self.chk_deblock = QCheckBox("Filtro de Desbloqueio e Redução de Ruído para Canais SD (Postproc 60fps)")
        self.chk_deblock.setChecked(getattr(parent, 'video_deblocking_enabled', True))
        video_layout.addWidget(self.chk_deblock)

        tip_video = QLabel("💡 Dica: Elimina o entrelaçamento e serrilhados de canais abertos com aceleração total da placa de vídeo.")
        tip_video.setStyleSheet("color: #64748b; font-size: 11px;")
        video_layout.addWidget(tip_video)

        layout.addWidget(video_group)

        # Rodapé
        btn_box = QHBoxLayout()
        btn_reset = QPushButton("↺ Restaurar Padrões")
        btn_reset.setProperty("class", "reset-btn")
        btn_reset.clicked.connect(self.reset_defaults)

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setProperty("class", "cancel-btn")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("✔ Salvar e Aplicar")
        btn_save.setProperty("class", "save-btn")
        btn_save.clicked.connect(self.save_and_apply)

        btn_box.addWidget(btn_reset)
        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)

    def reset_defaults(self):
        self.chk_normvol.setChecked(True)
        self.combo_audio_mode.setCurrentIndex(0)
        self.preamp_slider.setValue(6)
        self.combo_video_mode.setCurrentIndex(0)
        self.chk_deinterlace.setChecked(True)
        self.chk_deblock.setChecked(True)

    def save_and_apply(self):
        if self.parent:
            self.parent.audio_normalizer_enabled = self.chk_normvol.isChecked()
            self.parent.audio_mode = self.combo_audio_mode.currentData()
            self.parent.audio_preamp = float(self.preamp_slider.value())
            self.parent.video_mode = self.combo_video_mode.currentData()
            self.parent.video_deinterlace_enabled = self.chk_deinterlace.isChecked()
            self.parent.video_deblocking_enabled = self.chk_deblock.isChecked()
            
            self.parent.apply_audio_enhancements()
            self.parent.apply_video_enhancements()
            self.parent.save_settings()
            
            # Notifica na tela OSD
            ch_data = self.parent.all_channels[self.parent.current_channel_index]
            self.parent.show_tv_infobar(
                self.parent.current_channel_index + 1,
                ch_data['name'],
                "Áudio & Vídeo Calibrados com Sucesso",
                "✨ OTIMIZADO"
            )
        self.accept()


# =============================================================================

# =============================================================================
# JANELA PICTURE-IN-PICTURE (PIP) FLUTUANTE
# =============================================================================
class PiPVideoWindow(QWidget):
    """
    Mini-janela flutuante Picture-in-Picture (PiP) estilo Smart TV.
    Permite destacar o quadro de vídeo no canto da tela para continuar assistindo
    enquanto o usuário navega pelo Guia EPG ou Web Apps sem perder a transmissão.
    """
    def __init__(self, on_close_callback=None, on_expand_callback=None, parent=None):
        super().__init__(None)
        self.on_close_callback = on_close_callback
        self.on_expand_callback = on_expand_callback
        self.drag_position = None

        self.setWindowTitle("Picture-in-Picture - TutuTV Box")
        self.setWindowFlags(
            QtCore.Qt.WindowType.Tool |
            QtCore.Qt.WindowType.WindowStaysOnTopHint |
            QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(360, 202)  # Proporção 16:9
        self.setMinimumSize(280, 158)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame {
                background-color: #000000;
                border: 2px solid #38bdf8;
                border-radius: 10px;
            }
        """)
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(0)

        # Barra de controle do PiP
        self.top_bar = QFrame(self.container)
        self.top_bar.setFixedHeight(30)
        self.top_bar.setStyleSheet("""
            QFrame {
                background-color: rgba(15, 23, 42, 0.90);
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border-bottom: 1px solid rgba(56, 189, 248, 0.3);
            }
        """)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(8, 0, 6, 0)
        top_layout.setSpacing(6)

        self.lbl_title = QLabel("📺 PiP Ao Vivo", self.top_bar)
        self.lbl_title.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: bold; border: none; background: transparent;")

        btn_expand = QPushButton("⛶", self.top_bar)
        btn_expand.setFixedSize(22, 22)
        btn_expand.setToolTip("Restaurar para a tela principal")
        btn_expand.setCursor(QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        btn_expand.setStyleSheet("""
            QPushButton {
                background-color: rgba(56, 189, 248, 0.2);
                color: #38bdf8;
                border: 1px solid rgba(56, 189, 248, 0.4);
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #38bdf8;
                color: #0f172a;
            }
        """)
        btn_expand.clicked.connect(self.handle_expand)

        btn_close = QPushButton("✖", self.top_bar)
        btn_close.setFixedSize(22, 22)
        btn_close.setToolTip("Fechar PiP")
        btn_close.setCursor(QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: rgba(239, 68, 68, 0.2);
                color: #f87171;
                border: 1px solid rgba(239, 68, 68, 0.4);
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ef4444;
                color: #ffffff;
            }
        """)
        btn_close.clicked.connect(self.handle_close)

        top_layout.addWidget(self.lbl_title)
        top_layout.addStretch()
        top_layout.addWidget(btn_expand)
        top_layout.addWidget(btn_close)
        c_layout.addWidget(self.top_bar)

        # Superfície nativa onde o LibVLC renderiza o vídeo
        self.video_surface = QWidget(self.container)
        self.video_surface.setStyleSheet("background-color: #000000; border: none;")
        c_layout.addWidget(self.video_surface, stretch=1)

        layout.addWidget(self.container)

    def set_channel_name(self, name):
        clean_name = name[:26] + "..." if len(name) > 26 else name
        self.lbl_title.setText(f"📺 {clean_name}")

    def handle_expand(self):
        if self.on_expand_callback:
            self.on_expand_callback()
        else:
            self.hide()

    def handle_close(self):
        if self.on_close_callback:
            self.on_close_callback()
        else:
            self.hide()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.MouseButton.LeftButton and self.drag_position is not None:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_position = None
        event.accept()


# =============================================================================
# PAINEL DE DIAGNÓSTICO EM TEMPO REAL (ATALHO F12)
# =============================================================================
class DiagnosticDialog(QDialog):
    """
    Painel de Diagnóstico em Tempo Real (Atalho F12).
    Apresenta métricas de reprodução ao vivo, consumo de memória do processo,
    status da rede, estado LibVLC e console com os logs recentes da aplicação.
    """
    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.setWindowTitle("🛠️ Painel de Diagnóstico e Telemetria em Tempo Real")
        self.setMinimumSize(850, 620)
        self.resize(900, 650)
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0b0f19, stop:1 #020617);
                color: #f1f5f9;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }
            QGroupBox {
                border: 1px solid #1e293b;
                border-radius: 10px;
                margin-top: 14px;
                padding: 12px;
                font-size: 13px;
                font-weight: bold;
                color: #38bdf8;
                background-color: rgba(17, 24, 39, 0.7);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px;
            }
            QLabel {
                color: #cbd5e1;
                font-size: 12px;
            }
            QListWidget {
                background-color: #030712;
                border: 1px solid #1f2937;
                border-radius: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                padding: 6px;
            }
            QPushButton {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2563eb;
                border-color: #3b82f6;
            }
        """)

        self.init_ui()

        # Timer de atualização a cada 1000ms
        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self.update_metrics)
        self.refresh_timer.start()
        self.update_metrics()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        # Cabeçalho com título e indicador de status
        header_layout = QHBoxLayout()
        title_lbl = QLabel("🛠️ Diagnóstico do Sistema & Monitor de Estabilidade")
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #38bdf8;")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        self.lbl_diag_status = QLabel("● Telemetria Ativa")
        self.lbl_diag_status.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 12px;")
        header_layout.addWidget(self.lbl_diag_status)
        main_layout.addLayout(header_layout)

        # Cartões em 2 colunas: Transmissão / Hardware
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        # Coluna 1: Transmissão e Rede
        stream_box = QGroupBox("📡 Transmissão, Rede & Auto-Healing")
        stream_layout = QVBoxLayout(stream_box)
        stream_layout.setSpacing(6)

        self.lbl_channel_info = QLabel("Canal: --")
        self.lbl_vlc_state = QLabel("Estado LibVLC: --")
        self.lbl_buffer_mode = QLabel("Buffer Adaptativo: --")
        self.lbl_healing_stats = QLabel("Eventos de Auto-Healing: 0")
        self.lbl_stream_uptime = QLabel("Tempo de Reprodução Contínua: 0s")
        self.lbl_active_url = QLabel("URL Ativa: --")
        self.lbl_active_url.setWordWrap(True)
        self.lbl_active_url.setStyleSheet("color: #64748b; font-size: 11px;")

        for lbl in [self.lbl_channel_info, self.lbl_vlc_state, self.lbl_buffer_mode,
                    self.lbl_healing_stats, self.lbl_stream_uptime, self.lbl_active_url]:
            stream_layout.addWidget(lbl)
        cards_layout.addWidget(stream_box, stretch=1)

        # Coluna 2: Recursos do Sistema & Cache
        sys_box = QGroupBox("💻 Recursos do Sistema & Cache")
        sys_layout = QVBoxLayout(sys_box)
        sys_layout.setSpacing(6)

        self.lbl_memory = QLabel("Uso de Memória RAM: --")
        self.lbl_threads = QLabel("Threads Ativas: --")
        self.lbl_cache_status = QLabel("Cache M3U: --")
        self.lbl_pip_status = QLabel("Modo PiP: Inativo")
        self.lbl_zapping_stack = QLabel("Histórico Zapping: 0 canais")

        for lbl in [self.lbl_memory, self.lbl_threads, self.lbl_cache_status,
                    self.lbl_pip_status, self.lbl_zapping_stack]:
            sys_layout.addWidget(lbl)
        cards_layout.addWidget(sys_box, stretch=1)

        main_layout.addLayout(cards_layout)

        # Seção de Logs
        logs_box = QGroupBox("📋 Registro de Eventos e Logs Recentes (Rotação app.log)")
        logs_layout = QVBoxLayout(logs_box)
        logs_layout.setSpacing(8)

        # Barra de ferramentas dos logs
        tools_layout = QHBoxLayout()
        tools_layout.setSpacing(8)

        self.combo_log_filter = QComboBox()
        self.combo_log_filter.addItems(["Todos os Logs", "Apenas Avisos e Erros (WARN/ERROR)"])
        self.combo_log_filter.currentIndexChanged.connect(self.populate_logs)
        tools_layout.addWidget(self.combo_log_filter)

        tools_layout.addStretch()

        btn_force_heal = QPushButton("⚡ Testar Auto-Healing")
        btn_force_heal.setToolTip("Simula queda de sinal e dispara a troca automática para a URL de backup")
        btn_force_heal.clicked.connect(self.force_auto_healing)
        tools_layout.addWidget(btn_force_heal)

        btn_copy_logs = QPushButton("📋 Copiar Logs")
        btn_copy_logs.clicked.connect(self.copy_logs_to_clipboard)
        tools_layout.addWidget(btn_copy_logs)

        btn_clear_logs = QPushButton("🧹 Limpar")
        btn_clear_logs.clicked.connect(self.clear_logs)
        tools_layout.addWidget(btn_clear_logs)

        logs_layout.addLayout(tools_layout)

        self.log_list = QListWidget()
        logs_layout.addWidget(self.log_list)

        main_layout.addWidget(logs_box, stretch=1)

        # Botão Fechar
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        btn_close = QPushButton("Fechar [Esc]")
        btn_close.clicked.connect(self.close)
        bottom_layout.addWidget(btn_close)
        main_layout.addLayout(bottom_layout)

    def get_memory_usage_mb(self):
        try:
            if psutil:
                proc = psutil.Process()
                mem = proc.memory_info().rss / (1024 * 1024)
                return f"{mem:.1f} MB"
        except Exception:
            pass
        try:
            import ctypes
            from ctypes import wintypes
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ('cb', wintypes.DWORD),
                    ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t),
                    ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t),
                ]
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                mem = counters.WorkingSetSize / (1024 * 1024)
                return f"{mem:.1f} MB"
        except Exception:
            pass
        return "N/D"

    def update_metrics(self):
        mem_str = self.get_memory_usage_mb()
        self.lbl_memory.setText(f"Uso de Memória RAM: <b style='color:#38bdf8;'>{mem_str}</b>")
        self.lbl_threads.setText(f"Threads Ativas: <b>{threading.active_count()}</b>")

        if hasattr(self.player, 'all_channels') and 0 <= self.player.current_channel_index < len(self.player.all_channels):
            ch = self.player.all_channels[self.player.current_channel_index]
            self.lbl_channel_info.setText(f"Canal: <b>CH {self.player.current_channel_index+1:02d} - {ch['name']}</b> ({ch.get('group', 'Geral')})")
            urls = [ch['url']] + ch.get('fallback_urls', [])
            att = getattr(self.player, 'current_url_attempt', 0)
            url_str = urls[att] if att < len(urls) else ch['url']
            self.lbl_active_url.setText(f"URL Ativa (Tentativa {att}/{max(0, len(urls)-1)}): {url_str}")
        else:
            self.lbl_channel_info.setText("Canal: Nenhum canal selecionado")
            self.lbl_active_url.setText("URL: --")

        if hasattr(self.player, 'mediaplayer') and self.player.mediaplayer:
            try:
                state = self.player.mediaplayer.get_state()
                state_str = str(state).replace("State.", "")
                color = "#4ade80" if "Playing" in state_str else "#facc15" if "Buffering" in state_str else "#f87171"
                self.lbl_vlc_state.setText(f"Estado LibVLC: <b style='color:{color};'>{state_str}</b>")
            except Exception as e:
                self.lbl_vlc_state.setText(f"Estado LibVLC: Erro ({e})")

        curr_buf = getattr(self.player, 'current_buffer_ms', 800)
        mode = "Adaptativo / Resiliente" if curr_buf >= 2000 else "Baixa Latência (Estável)"
        color_buf = "#facc15" if curr_buf >= 2000 else "#4ade80"
        self.lbl_buffer_mode.setText(f"Buffer de Rede: <b style='color:{color_buf};'>{curr_buf}ms</b> ({mode})")

        heals = getattr(self.player, 'auto_heal_counter', 0)
        self.lbl_healing_stats.setText(f"Auto-Healings Disparados: <b>{heals}</b>")

        last_start = getattr(self.player, 'stream_start_timestamp', time.time())
        if getattr(self.player, 'is_playing', False):
            elapsed = int(time.time() - last_start)
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            self.lbl_stream_uptime.setText(f"Tempo de Reprodução Contínua: <b style='color:#38bdf8;'>{h:02d}:{m:02d}:{s:02d}</b>")
        else:
            self.lbl_stream_uptime.setText("Tempo de Reprodução Contínua: <b style='color:#94a3b8;'>Pausado</b>")

        is_pip = getattr(self.player, 'is_pip_active', False)
        self.lbl_pip_status.setText(f"Modo PiP: <b style='color:{'#38bdf8' if is_pip else '#94a3b8'};'>{'Ativo (Flutuante)' if is_pip else 'Inativo'}</b>")

        hist_len = len(getattr(self.player, 'zapping_history', []))
        self.lbl_zapping_stack.setText(f"Histórico Zapping (Recall): <b>{hist_len} canais na pilha</b>")

        if os.path.exists(CACHE_FILE):
            try:
                mtime = os.path.getmtime(CACHE_FILE)
                age_h = (time.time() - mtime) / 3600.0
                status_color = "#4ade80" if age_h < 24 else "#facc15"
                self.lbl_cache_status.setText(f"Cache M3U Local: <b style='color:{status_color};'>{age_h:.1f}h de idade ({'Válido <24h' if age_h < 24 else 'Expirado >24h'})</b>")
            except Exception:
                self.lbl_cache_status.setText("Cache M3U Local: Presente")
        else:
            self.lbl_cache_status.setText("Cache M3U Local: <b style='color:#f87171;'>Não criado</b>")

        self.populate_logs()

    def populate_logs(self):
        records = in_memory_log_handler.get_records()
        filter_idx = self.combo_log_filter.currentIndex()

        self.log_list.clear()
        for rec in reversed(records[-100:]):
            lvl = rec['level']
            if filter_idx == 1 and lvl not in ('WARNING', 'ERROR'):
                continue

            item = QListWidgetItem(f"[{rec['time_str']}] [{lvl:<7}] {rec['message']}")
            if lvl == 'ERROR':
                item.setForeground(QtCore.Qt.GlobalColor.red)
            elif lvl == 'WARNING':
                item.setForeground(QtCore.Qt.GlobalColor.yellow)
            elif lvl == 'INFO':
                item.setForeground(QtCore.Qt.GlobalColor.cyan)
            else:
                item.setForeground(QtCore.Qt.GlobalColor.gray)
            self.log_list.addItem(item)

    def force_auto_healing(self):
        logger.info("Usuário disparou teste manual de Auto-Healing via Painel de Diagnóstico.")
        if hasattr(self.player, 'trigger_auto_healing'):
            self.player.trigger_auto_healing(reason="Teste Manual de Auto-Healing via Diagnóstico F12")
            self.update_metrics()

    def copy_logs_to_clipboard(self):
        records = in_memory_log_handler.get_records()
        text = "\n".join([r['formatted'] for r in records])
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Logs Copiados", f"{len(records)} linhas de log foram copiadas para a área de transferência!")

    def clear_logs(self):
        in_memory_log_handler.clear()
        self.log_list.clear()


# =============================================================================
# DOWNLOADER ASSÍNCRONO DA LISTA M3U COM VALIDAÇÃO POR LOTES (CHUNKING)
# =============================================================================
class M3UDownloader(QtCore.QThread):
    finished_signal = QtCore.pyqtSignal(list, set)

    def __init__(self, url, max_workers=6):
        super().__init__()
        self.url = url
        self.max_workers = max_workers

    def run(self):
        logger.info(f"M3UDownloader: Iniciando download da lista a partir de '{self.url}'...")
        m3u_channels = []
        categories = set()

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        try:
            session = requests.Session()
            response = session.get(self.url, headers=headers, timeout=(4.0, 12.0))
            response.encoding = 'utf-8'
            lines = response.text.splitlines()

            current_name = ""
            current_group = "Geral"

            for line in lines:
                line = line.strip()
                if line.startswith("#EXTINF:"):
                    group_match = re.search(r'group-title="([^"]+)"', line, re.IGNORECASE)
                    if group_match:
                        raw_group = group_match.group(1).strip()
                        primary_cat = raw_group.split(';')[0].strip()
                        current_group = CATEGORY_TRANSLATIONS.get(primary_cat, primary_cat)
                    else:
                        current_group = "Geral"

                    if "," in line:
                        current_name = line.rsplit(",", 1)[1].strip()

                elif line.startswith("http") and current_name:
                    m3u_channels.append({
                        'name': current_name,
                        'url': line,
                        'fallback_urls': [],
                        'group': current_group,
                        'badge': 'IPTV • VERIFICADO'
                    })
                    current_name = ""
                    current_group = "Geral"

            logger.info(f"M3UDownloader: {len(m3u_channels)} canais brutos encontrados. Iniciando validação assíncrona por lotes (Chunking)...")

            # Validação assíncrona otimizada com limitação de workers e processamento em lotes (Chunking)
            def verify_stream(ch):
                try:
                    res = session.get(ch['url'], headers=headers, timeout=(2.0, 3.5), stream=True)
                    if res.status_code == 200:
                        first_chunk = next(res.iter_content(512), b"")
                        if (b"#EXTM3U" in first_chunk or 
                            b"#EXT-X" in first_chunk or 
                            res.headers.get("content-type", "").startswith(("application", "video", "audio"))):
                            return ch
                except Exception as ex:
                    logger.debug(f"Stream inválido ou offline '{ch['name']}': {ex}")
                return None

            validated_channels = []
            if m3u_channels:
                # Processamento em lotes de 18 para evitar saturação de recursos
                BATCH_SIZE = 18
                chunks = [m3u_channels[i:i + BATCH_SIZE] for i in range(0, len(m3u_channels), BATCH_SIZE)]
                
                # Limite estrito de 6 workers paralelos para TV Boxes de baixo desempenho
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    for b_idx, chunk in enumerate(chunks, start=1):
                        logger.debug(f"Validando lote {b_idx}/{len(chunks)} ({len(chunk)} canais)...")
                        results = executor.map(verify_stream, chunk)
                        for valid_ch in results:
                            if valid_ch:
                                validated_channels.append(valid_ch)

                logger.info(f"M3UDownloader: Validação concluída. {len(validated_channels)}/{len(m3u_channels)} canais validados e ativos.")
                m3u_channels = validated_channels
                for ch in m3u_channels:
                    categories.add(ch['group'])

                # Salva no cache local com carimbo de data/hora (TTL de 24 horas)
                save_channels_cache(m3u_channels, categories, self.url)

        except Exception as e:
            logger.error(f"Erro no download ou processamento M3U: {e}", exc_info=True)

        self.finished_signal.emit(m3u_channels, categories)


# =============================================================================
# APLICATIVO PRINCIPAL (TUTUTV BOX BRASIL)
# =============================================================================
class IPTVPlayerBR(QMainWindow):
    vlc_playing_signal = QtCore.pyqtSignal()
    vlc_error_signal = QtCore.pyqtSignal()
    vlc_buffering_signal = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__()

        logger.info("Iniciando TutuTV Box Brasil...")
        self.setWindowTitle("TutuTV Box Brasil - Experiência de Televisão Digital")
        self.setMinimumSize(1200, 720)

        self.favorites_urls = set()
        self.custom_channels = []
        self.youtube_favs = []
        self.current_volume = 100
        self.is_muted = False
        self.pre_mute_volume = 100
        self.is_playing = False
        self.number_buffer = ""
        self.number_timer = QtCore.QTimer(self)
        self.number_timer.setSingleShot(True)
        self.number_timer.timeout.connect(self.commit_number_jump)

        # Configurações de Otimização Smart TV (Áudio & Vídeo)
        self.audio_normalizer_enabled = True
        self.audio_mode = "smart"  # smart, dialogue, flat
        self.audio_preamp = 6.0    # Ganho pré-amplificador para canais silenciosos
        self.audio_max_level = 2.5
        self.video_mode = "vivid"  # vivid, cinema, 4:3
        self.video_deinterlace_enabled = True
        self.video_deblocking_enabled = True
        self.current_eq = None

        # Histórico de Zapping ("Recall" / Últimos 5 canais)
        self.zapping_history = deque(maxlen=5)

        # Buffer Adaptativo Dinâmico (800ms em conexões estáveis, 3000ms em oscilação)
        self.current_buffer_ms = 800
        self.recent_buffering_timestamps = deque(maxlen=20)
        self.last_buffer_adapt_timestamp = time.time()

        # Telemetria, Watchdog de Resiliência e Auto-Healing em Tempo Real
        self.stream_start_timestamp = time.time()
        self.last_playback_progress_timestamp = time.time()
        self.last_media_time = -1
        self.consecutive_freeze_seconds = 0
        self.auto_healing_in_progress = False
        self.auto_heal_counter = 0
        self.auto_heal_attempts_on_channel = 0
        self.current_url_attempt = 0

        # Modo Picture-in-Picture (PiP)
        self.is_pip_active = False

        self.load_settings()

        # Conexão de sinais VLC de forma segura com a thread da interface gráfica
        self.vlc_playing_signal.connect(self.on_vlc_playing)
        self.vlc_error_signal.connect(self.on_vlc_error)
        self.vlc_buffering_signal.connect(self.on_vlc_buffering)

        # Configurações otimizadas do VLC para HLS e Live Streaming
        vlc_args = [
            "--no-xlib",
            "--quiet",
            f"--network-caching={self.current_buffer_ms}",
            f"--live-caching={self.current_buffer_ms}",
            "--clock-jitter=0",
            "--clock-synchro=0",
            "--drop-late-frames",
            "--skip-frames",
            "--avcodec-hw=any",
            "--deinterlace=1",
            "--deinterlace-mode=yadif2x",
            "--postproc-q=6",
            "--audio-filter=normvol",
            "--norm-max-level=2.5",
            "--norm-buff-size=10"
        ]

        if not vlc:
            logger.critical("Módulo VLC não encontrado no sistema.")
            QMessageBox.critical(
                self,
                "VLC Media Player Não Encontrado",
                "O módulo VLC não foi detectado no sistema.\n\n"
                "Para assistir aos canais, instale a versão oficial do VLC 64-bit em:\n"
                "https://www.videolan.org/vlc/"
            )
            sys.exit(1)

        try:
            self.instance = vlc.Instance(vlc_args)
            if not self.instance:
                self.instance = vlc.Instance()
            self.mediaplayer = self.instance.media_player_new()
            self.event_manager = self.mediaplayer.event_manager()

            # Callbacks protegidos com tratamento defensivo
            def safe_playing_callback(event):
                try:
                    self.vlc_playing_signal.emit()
                except Exception as ex:
                    logger.debug(f"Erro no safe_playing_callback: {ex}")

            def safe_error_callback(event):
                try:
                    self.vlc_error_signal.emit()
                except Exception as ex:
                    logger.debug(f"Erro no safe_error_callback: {ex}")

            def safe_buffering_callback(event):
                try:
                    cache_val = int(getattr(event.u, 'new_cache', 100))
                    self.vlc_buffering_signal.emit(cache_val)
                except Exception as ex:
                    logger.debug(f"Erro no safe_buffering_callback: {ex}")

            self.event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, safe_playing_callback)
            self.event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, safe_error_callback)
            self.event_manager.event_attach(vlc.EventType.MediaPlayerBuffering, safe_buffering_callback)

        except Exception as e:
            logger.critical(f"Erro ao inicializar player VLC: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Erro ao Iniciar o Player VLC",
                f"Não foi possível iniciar o mecanismo de vídeo:\n{e}\n\n"
                "Verifique se o VLC 64-bit está instalado na pasta padrão."
            )
            sys.exit(1)

        self.safe_vlc_call(self.mediaplayer.audio_set_volume, self.current_volume)

        # Carrega canais abertos nativos + canais personalizados do usuário
        self.all_channels = list(CANAIS_ABERTOS_BRASIL) + self.custom_channels
        self.categories = set(["TV Aberta Brasil"])
        for ch in self.custom_channels:
            self.categories.add(ch.get('group', 'Personalizados'))

        # Cache Local M3U com TTL (24 horas) para abertura offline imediata
        cached_chs, cached_cats, is_fresh, cache_age = load_channels_cache()
        existing_urls = {c['url'] for c in self.all_channels}
        if cached_chs:
            for ch in cached_chs:
                if ch['url'] not in existing_urls:
                    self.all_channels.append(ch)
                    existing_urls.add(ch['url'])
            self.categories.update(cached_cats)

        self.current_channel_index = 0
        self.is_fullscreen = False

        # Aplica estilos modernos e inicializa interface gráfica
        self.apply_theme_styles()
        self.init_ui()

        # Janela Picture-in-Picture (PiP)
        self.pip_window = PiPVideoWindow(
            on_close_callback=self.disable_pip_mode,
            on_expand_callback=self.disable_pip_mode,
            parent=self
        )

        # Animação suave e timers de OSD
        self.opacity_effect = QGraphicsOpacityEffect(self.tv_infobar)
        self.tv_infobar.setGraphicsEffect(self.opacity_effect)
        
        self.fade_animation = QtCore.QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_animation.setDuration(700)
        self.fade_animation.setStartValue(1.0)
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.finished.connect(self.tv_infobar.hide)

        self.overlay_timer = QtCore.QTimer(self)
        self.overlay_timer.setSingleShot(True)
        self.overlay_timer.timeout.connect(self.start_infobar_fadeout)

        # Relógio da TV atualizado a cada segundo
        self.clock_timer = QtCore.QTimer(self)
        self.clock_timer.setInterval(1000)
        self.clock_timer.timeout.connect(self.update_tv_clock)
        self.clock_timer.start()

        # Watchdog de Resiliência e Auto-Healing em Tempo Real (verifica a cada 1000ms)
        self.stream_watchdog_timer = QtCore.QTimer(self)
        self.stream_watchdog_timer.setInterval(1000)
        self.stream_watchdog_timer.timeout.connect(self.stream_watchdog_check)
        self.stream_watchdog_timer.start()

        # Filtro global de atalhos e controle de TV Box
        qapp = QApplication.instance()
        qapp.installEventFilter(self)

        self.populate_categories_and_channels()

        # Sintoniza imediatamente o primeiro canal aberto
        QtCore.QTimer.singleShot(100, lambda: self.play_channel_by_index(0))

        # Se o cache tiver menos de 24 horas, abre offline imediatamente!
        if is_fresh:
            logger.info(f"Cache local M3U válido (<24h, idade: {cache_age:.1f}h). Inicialização offline imediata concluída.")
        else:
            logger.info(f"Cache M3U expirado ou inexistente ({cache_age:.1f}h). Disparando download em segundo plano...")
            self.start_m3u_download("https://iptv-org.github.io/iptv/countries/br.m3u")

    def safe_vlc_call(self, func, *args, default=None, error_msg="Erro em chamada nativa LibVLC"):
        """Invoca métodos nativos da LibVLC protegendo a aplicação contra travamentos de DLL e exceções C."""
        try:
            if func is None:
                return default
            return func(*args)
        except Exception as e:
            logger.error(f"{error_msg} ({getattr(func, '__name__', str(func))}): {e}", exc_info=True)
            return default

    def apply_theme_styles(self):
        """Aplica estilo moderno Smart TV Dark Theme com glassmorphism e cores harmoniosas."""
        self.setStyleSheet("""
            QMainWindow { background-color: #0b0f19; }
            QWidget { 
                color: #f1f5f9; 
                font-family: 'Segoe UI', -apple-system, sans-serif; 
                font-size: 14px;
            }
            
            #sidebar {
                background-color: #0f172a;
                border-right: 1px solid #1e293b;
            }
            #sidebar QPushButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 12px;
                padding: 10px;
                font-size: 20px;
            }
            #sidebar QPushButton:hover { 
                background-color: #1e293b; 
                border: 1px solid #334155;
            }
            #sidebar QPushButton:focus { 
                background-color: #2563eb; 
            }

            QLineEdit {
                background-color: #111827;
                border: 1px solid #1f2937;
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 14px;
                color: #ffffff;
            }
            QLineEdit:focus { 
                border: 1px solid #3b82f6;
                background-color: #1f2937;
            }

            QComboBox {
                background-color: #111827;
                border: 1px solid #1f2937;
                border-radius: 10px;
                padding: 9px 14px;
                font-size: 14px;
                font-weight: 500;
                color: #f1f5f9;
                min-height: 22px;
            }
            QComboBox:hover { border: 1px solid #374151; background-color: #1a2234; }
            QComboBox:focus { border: 1px solid #3b82f6; }
            QComboBox::drop-down { border: none; width: 30px; }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #94a3b8;
                margin-right: 10px;
            }

            QComboBox QAbstractItemView {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 4px;
                outline: 0;
                font-size: 14px;
                color: #e2e8f0;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QComboBox QAbstractItemView::item {
                min-height: 34px;
                padding-left: 10px;
                border-radius: 6px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #1e293b;
                color: #ffffff;
            }
            
            QListWidget { 
                background-color: transparent; 
                border: none; 
                outline: 0; 
            }
            QListWidget::item {
                background-color: #111827;
                border-radius: 10px;
                margin: 4px 2px;
                padding: 10px 14px;
                border: 1px solid #1f2937;
                font-size: 14px;
                font-weight: 600;
            }
            QListWidget::item:hover { 
                background-color: #1e293b; 
                border: 1px solid #334155; 
            }
            QListWidget::item:focus, QListWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #1d4ed8);
                border: 1px solid #60a5fa;
                color: #ffffff;
                font-weight: bold;
            }

            #epg_panel, #web_control_bar {
                background-color: #0f172a;
                border-radius: 14px;
                border: 1px solid #1e293b;
            }

            QSlider::groove:horizontal { height: 6px; background: #1e293b; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 3px; }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
            
            #tv_infobar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(15, 23, 42, 0.94), stop:1 rgba(11, 15, 25, 0.98));
                border: 1px solid rgba(59, 130, 246, 0.6);
                border-left: 6px solid #3b82f6;
                border-radius: 14px;
                padding: 14px 22px;
            }
            #channel_number {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #1d4ed8);
                color: #ffffff;
                font-weight: bold;
                font-size: 18px;
                padding: 8px 16px;
                border-radius: 8px;
            }
            #channel_title { color: #ffffff; font-size: 20px; font-weight: bold; }
            #channel_category { color: #94a3b8; font-size: 13px; }
            #channel_badge {
                color: #38bdf8;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #0284c7;
                border-radius: 6px;
                padding: 5px 12px;
                background-color: rgba(2, 132, 199, 0.2);
            }

            QPushButton.ctrl-btn {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 7px 14px;
                font-weight: 600;
                color: #f1f5f9;
            }
            QPushButton.ctrl-btn:hover {
                background-color: #334155;
                border-color: #475569;
            }
            QPushButton.ctrl-btn:pressed {
                background-color: #2563eb;
            }
            QPushButton.accent-btn {
                background-color: #2563eb;
                border: 1px solid #3b82f6;
                border-radius: 8px;
                padding: 7px 14px;
                font-weight: bold;
                color: #ffffff;
            }
            QPushButton.accent-btn:hover {
                background-color: #1d4ed8;
            }
        """)

    def load_settings(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.favorites_urls = set(data.get("favorites", []))
                    self.custom_channels = data.get("custom_channels", [])
                    self.youtube_favs = data.get("youtube_favs", [])
                    self.current_volume = data.get("volume", 100)
                    self.audio_normalizer_enabled = data.get("audio_normalizer", True)
                    self.audio_mode = data.get("audio_mode", "smart")
                    self.audio_preamp = float(data.get("audio_preamp", 6.0))
                    self.video_mode = data.get("video_mode", "vivid")
                    self.video_deinterlace_enabled = data.get("video_deinterlace", True)
                    self.video_deblocking_enabled = data.get("video_deblocking", True)
                logger.info(f"Configurações carregadas com sucesso de '{CONFIG_FILE}'")
            except Exception as e:
                logger.error(f"Erro ao carregar configurações de '{CONFIG_FILE}': {e}", exc_info=True)

    def save_settings(self):
        try:
            data = {
                "favorites": list(self.favorites_urls),
                "custom_channels": self.custom_channels,
                "youtube_favs": self.youtube_favs,
                "volume": self.current_volume,
                "audio_normalizer": getattr(self, 'audio_normalizer_enabled', True),
                "audio_mode": getattr(self, 'audio_mode', 'smart'),
                "audio_preamp": getattr(self, 'audio_preamp', 6.0),
                "video_mode": getattr(self, 'video_mode', 'vivid'),
                "video_deinterlace": getattr(self, 'video_deinterlace_enabled', True),
                "video_deblocking": getattr(self, 'video_deblocking_enabled', True)
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info(f"Configurações salvas com sucesso em '{CONFIG_FILE}'")
        except Exception as e:
            logger.error(f"Erro ao salvar configurações em '{CONFIG_FILE}': {e}", exc_info=True)

    def update_tv_clock(self):
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")
        self.tv_clock_lbl.setText(f"🕒 {time_str}")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.root_layout = QHBoxLayout(central_widget)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        # BARRA LATERAL (MENU DE NAVEGAÇÃO E APLICATIVOS)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(72)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 16, 10, 16)
        sidebar_layout.setSpacing(12)

        btn_tv = QPushButton("📺")
        btn_tv.setToolTip("TV Ao Vivo (Canais Abertos)")
        btn_tv.clicked.connect(self.open_tv_mode)

        btn_guide = QPushButton("📅")
        btn_guide.setToolTip("Guia de Programação (Tecla G)")
        btn_guide.clicked.connect(self.open_tv_guide)

        btn_yt = QPushButton("▶️")
        btn_yt.setToolTip("YouTube")
        btn_yt.clicked.connect(lambda: self.open_web_app("https://www.youtube.com"))

        btn_pluto = QPushButton("🍿")
        btn_pluto.setToolTip("Pluto TV Brasil (100+ Canais Gratuitos)")
        btn_pluto.clicked.connect(lambda: self.open_web_app("https://pluto.tv/br/live-tv"))

        btn_globo = QPushButton("🌐")
        btn_globo.setToolTip("Globoplay (TV Aberta Grátis)")
        btn_globo.clicked.connect(lambda: self.open_web_app("https://globoplay.globo.com/agora-na-tv/"))

        btn_nfx = QPushButton("🎬")
        btn_nfx.setToolTip("Netflix")
        btn_nfx.clicked.connect(lambda: self.open_web_app("https://www.netflix.com"))

        btn_amz = QPushButton("📦")
        btn_amz.setToolTip("Prime Video")
        btn_amz.clicked.connect(lambda: self.open_web_app("https://www.primevideo.com"))

        btn_add_ch = QPushButton("➕")
        btn_add_ch.setToolTip("Adicionar Canal Personalizado")
        btn_add_ch.clicked.connect(self.prompt_add_custom_channel)

        for btn in [btn_tv, btn_guide, btn_yt, btn_pluto, btn_globo, btn_nfx, btn_amz, btn_add_ch]:
            sidebar_layout.addWidget(btn)
        sidebar_layout.addStretch()
        self.root_layout.addWidget(self.sidebar)

        # STACK DE TELAS (IPTV OU APLICATIVOS WEB)
        self.stack = QStackedWidget()
        self.root_layout.addWidget(self.stack)

        # TELA 0: REPRODUTOR DE TV AO VIVO
        self.iptv_widget = QWidget()
        self.content_layout = QHBoxLayout(self.iptv_widget)
        self.content_layout.setContentsMargins(14, 14, 14, 14)
        self.content_layout.setSpacing(14)

        # PAINEL ESQUERDO: LISTA DE CANAIS E PESQUISA
        self.left_panel = QWidget()
        self.left_panel.setFixedWidth(380)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # Barra de Pesquisa com botão de limpar
        search_box = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("🔍 Pesquisar canal aberto...")
        self.search_bar.textChanged.connect(self.filter_channels)
        search_box.addWidget(self.search_bar)
        
        btn_clear_search = QPushButton("✖")
        btn_clear_search.setToolTip("Limpar busca")
        btn_clear_search.setFixedWidth(36)
        btn_clear_search.setProperty("class", "ctrl-btn")
        btn_clear_search.clicked.connect(lambda: self.search_bar.clear())
        search_box.addWidget(btn_clear_search)
        left_layout.addLayout(search_box)

        # Filtro de Categorias em PT-BR
        self.category_combo = QComboBox()
        self.category_combo.setMaxVisibleItems(12)
        self.category_combo.currentIndexChanged.connect(self.filter_channels)
        left_layout.addWidget(self.category_combo)

        # Contador de canais
        self.lbl_channel_count = QLabel("Carregando canais...")
        self.lbl_channel_count.setStyleSheet("color: #94a3b8; font-size: 12px; margin-left: 4px;")
        left_layout.addWidget(self.lbl_channel_count)

        # Lista de Canais
        self.channel_grid = QListWidget()
        self.channel_grid.setViewMode(QListWidget.ViewMode.ListMode)
        self.channel_grid.setSpacing(2)
        self.channel_grid.itemClicked.connect(self.play_channel_by_item)
        self.channel_grid.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.channel_grid.customContextMenuRequested.connect(self.toggle_favorite_context)
        left_layout.addWidget(self.channel_grid)

        self.content_layout.addWidget(self.left_panel)

        # PAINEL DIREITO: VÍDEO E CONTROLES DE TV
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(12)

        # Quadro do Reprodutor de Vídeo VLC
        self.video_frame = QWidget()
        self.video_frame.setStyleSheet("background-color: #000000; border-radius: 14px;")
        self.video_frame.setCursor(QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        
        self.video_container_layout = QVBoxLayout(self.video_frame)
        self.video_container_layout.setContentsMargins(20, 20, 20, 20)

        # Barra do Topo da TV (Relógio Digital e Indicador de Canal)
        tv_top_bar = QHBoxLayout()
        self.tv_ch_quick_tag = QLabel("CH 01 • SBT Nacional")
        self.tv_ch_quick_tag.setStyleSheet("""
            background-color: rgba(15, 23, 42, 0.75);
            color: #38bdf8;
            font-weight: bold;
            font-size: 13px;
            padding: 6px 12px;
            border-radius: 8px;
            border: 1px solid rgba(59, 130, 246, 0.4);
        """)

        self.tv_clock_lbl = QLabel("🕒 00:00:00")
        self.tv_clock_lbl.setStyleSheet("""
            background-color: rgba(15, 23, 42, 0.75);
            color: #f8fafc;
            font-weight: bold;
            font-size: 13px;
            padding: 6px 12px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        """)

        tv_top_bar.addWidget(self.tv_ch_quick_tag)
        tv_top_bar.addStretch()
        tv_top_bar.addWidget(self.tv_clock_lbl)
        self.video_container_layout.addLayout(tv_top_bar)

        self.video_container_layout.addStretch()

        # Banner informativo de Picture-in-Picture no quadro de vídeo principal
        self.pip_active_banner = QLabel("🖼️ Transmissão Ativa no Modo Picture-in-Picture (PiP)\nClique aqui ou pressione [P] para restaurar o vídeo")
        self.pip_active_banner.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.pip_active_banner.setStyleSheet("""
            background-color: rgba(15, 23, 42, 0.92);
            color: #38bdf8;
            font-size: 15px;
            font-weight: bold;
            border: 2px dashed #38bdf8;
            border-radius: 12px;
            padding: 24px;
        """)
        self.pip_active_banner.hide()
        self.pip_active_banner.mousePressEvent = lambda e: self.disable_pip_mode()
        self.video_container_layout.addWidget(self.pip_active_banner)

        self.video_container_layout.addStretch()

        # HUD / BARRA DE INFORMAÇÕES DE TV COM EPG (ON-SCREEN DISPLAY)
        self.tv_infobar = QFrame()
        self.tv_infobar.setObjectName("tv_infobar")
        self.tv_infobar.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        infobar_vlayout = QVBoxLayout(self.tv_infobar)
        infobar_vlayout.setContentsMargins(18, 14, 18, 14)
        infobar_vlayout.setSpacing(10)

        # Linha 1: Número, Nome e Badge de Qualidade
        top_info_row = QHBoxLayout()
        self.lbl_ch_num = QLabel("CH 001")
        self.lbl_ch_num.setObjectName("channel_number")

        info_channel_names = QVBoxLayout()
        info_channel_names.setSpacing(2)
        self.lbl_ch_title = QLabel("Nome do Canal")
        self.lbl_ch_title.setObjectName("channel_title")

        self.lbl_ch_cat = QLabel("TV Aberta • Transmissão Digital")
        self.lbl_ch_cat.setObjectName("channel_category")
        info_channel_names.addWidget(self.lbl_ch_title)
        info_channel_names.addWidget(self.lbl_ch_cat)

        self.lbl_ch_badge = QLabel("1080p • AO VIVO")
        self.lbl_ch_badge.setObjectName("channel_badge")

        self.lbl_enhancement_badge = QLabel("🔊 ÁUDIO NIVELADO  •  ✨ SMART HD")
        self.lbl_enhancement_badge.setStyleSheet("background-color: rgba(14, 165, 233, 0.2); color: #38bdf8; font-size: 11px; font-weight: bold; border-radius: 4px; padding: 2px 8px; border: 1px solid rgba(56, 189, 248, 0.4);")

        top_info_row.addWidget(self.lbl_ch_num)
        top_info_row.addLayout(info_channel_names)
        top_info_row.addStretch()
        top_info_row.addWidget(self.lbl_enhancement_badge)
        top_info_row.addWidget(self.lbl_ch_badge)
        infobar_vlayout.addLayout(top_info_row)

        # Linha 2: Programa no Ar e Barra de Progresso
        self.lbl_osd_current_prog = QLabel("🔴 NO AR: Carregando Programação...")
        self.lbl_osd_current_prog.setStyleSheet("color: #ffffff; font-size: 15px; font-weight: bold;")
        infobar_vlayout.addWidget(self.lbl_osd_current_prog)

        osd_prog_bar_layout = QHBoxLayout()
        self.osd_progress_bar = QProgressBar()
        self.osd_progress_bar.setRange(0, 100)
        self.osd_progress_bar.setValue(50)
        self.osd_progress_bar.setTextVisible(False)
        self.osd_progress_bar.setFixedHeight(5)
        self.osd_progress_bar.setStyleSheet("""
            QProgressBar { background-color: #1e293b; border-radius: 2px; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38bdf8, stop:1 #2563eb); border-radius: 2px; }
        """)

        self.lbl_osd_remaining = QLabel("Faltam 30 min")
        self.lbl_osd_remaining.setStyleSheet("color: #94a3b8; font-size: 11px;")
        osd_prog_bar_layout.addWidget(self.osd_progress_bar, stretch=1)
        osd_prog_bar_layout.addWidget(self.lbl_osd_remaining)
        infobar_vlayout.addLayout(osd_prog_bar_layout)

        # Linha 3: O Que Vem a Seguir
        self.lbl_osd_next_prog = QLabel("⏭️ A SEGUIR: Próximo programa")
        self.lbl_osd_next_prog.setStyleSheet("color: #cbd5e1; font-size: 13px; font-weight: 500;")
        infobar_vlayout.addWidget(self.lbl_osd_next_prog)

        self.tv_infobar.hide()
        self.video_container_layout.addWidget(self.tv_infobar)

        self.right_layout.addWidget(self.video_frame, stretch=4)

        # PAINEL INFERIOR: GUIA EPG AO VIVO + CONTROLES
        self.epg_panel = QFrame()
        self.epg_panel.setObjectName("epg_panel")
        epg_main_layout = QHBoxLayout(self.epg_panel)
        epg_main_layout.setContentsMargins(16, 12, 16, 12)
        epg_main_layout.setSpacing(18)

        # Coluna 1: Controles de Reprodução e Volume
        ctrl_col = QVBoxLayout()
        ctrl_col.setSpacing(8)

        epg_header_layout = QHBoxLayout()
        self.epg_title = QLabel("📺 Sintonizando TV Aberta...")
        self.epg_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        
        self.status_badge = QLabel("🟢 Conectando...")
        self.status_badge.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 12px;")

        epg_header_layout.addWidget(self.epg_title)
        epg_header_layout.addStretch()
        epg_header_layout.addWidget(self.status_badge)
        ctrl_col.addLayout(epg_header_layout)

        ctrl_bar_layout = QHBoxLayout()
        ctrl_bar_layout.setSpacing(6)

        self.btn_prev = QPushButton("⏮️")
        self.btn_prev.setProperty("class", "ctrl-btn")
        self.btn_prev.setToolTip("Canal Anterior (Seta Cima)")
        self.btn_prev.clicked.connect(self.prev_channel)

        self.btn_play_pause = QPushButton("⏸️ Pausar")
        self.btn_play_pause.setProperty("class", "accent-btn")
        self.btn_play_pause.setToolTip("Pausar / Retomar (Espaço)")
        self.btn_play_pause.clicked.connect(self.toggle_play_pause)

        self.btn_next = QPushButton("⏭️")
        self.btn_next.setProperty("class", "ctrl-btn")
        self.btn_next.setToolTip("Próximo Canal (Seta Baixo)")
        self.btn_next.clicked.connect(self.next_channel)

        self.btn_recall = QPushButton("↩ Recall")
        self.btn_recall.setProperty("class", "ctrl-btn")
        self.btn_recall.setToolTip("Alternar com Canal Anterior / Zapping History [Backspace]")
        self.btn_recall.clicked.connect(self.recall_last_channel)

        self.btn_reload = QPushButton("🔄")
        self.btn_reload.setProperty("class", "ctrl-btn")
        self.btn_reload.setToolTip("Recarregar Sinal do Canal (R)")
        self.btn_reload.clicked.connect(self.reload_current_channel)

        self.btn_guide_quick = QPushButton("📅 Guia EPG")
        self.btn_guide_quick.setProperty("class", "ctrl-btn")
        self.btn_guide_quick.setToolTip("Abrir Guia de Programação Completo (G)")
        self.btn_guide_quick.clicked.connect(self.open_tv_guide)

        self.btn_av_settings = QPushButton("✨ Otimizador A/V")
        self.btn_av_settings.setProperty("class", "ctrl-btn")
        self.btn_av_settings.setToolTip("Otimizador de Imagem HD e Nivelador de Volume [Atalho O]")
        self.btn_av_settings.clicked.connect(self.open_av_settings_dialog)

        self.btn_audio_mode_quick = QPushButton("🔊 Nivelar")
        self.btn_audio_mode_quick.setProperty("class", "ctrl-btn")
        self.btn_audio_mode_quick.setToolTip("Alternar Modo de Áudio (Canais Baixos Equalizados) [Atalho A]")
        self.btn_audio_mode_quick.clicked.connect(self.cycle_audio_mode)

        self.btn_video_mode_quick = QPushButton("✨ Vívido")
        self.btn_video_mode_quick.setProperty("class", "ctrl-btn")
        self.btn_video_mode_quick.setToolTip("Alternar Modo de Imagem Smart TV [Atalho V]")
        self.btn_video_mode_quick.clicked.connect(self.cycle_picture_mode)

        self.btn_pip = QPushButton("🖼️ PiP")
        self.btn_pip.setProperty("class", "ctrl-btn")
        self.btn_pip.setToolTip("Alternar Modo Picture-in-Picture [Atalho P]")
        self.btn_pip.clicked.connect(self.toggle_pip_mode)

        self.btn_diag = QPushButton("🛠️ Diagnóstico")
        self.btn_diag.setProperty("class", "ctrl-btn")
        self.btn_diag.setToolTip("Painel de Diagnóstico e Telemetria em Tempo Real [Atalho F12]")
        self.btn_diag.clicked.connect(self.open_diagnostic_dialog)

        self.btn_fav = QPushButton("⭐")
        self.btn_fav.setProperty("class", "ctrl-btn")
        self.btn_fav.setToolTip("Favoritar Canal")
        self.btn_fav.clicked.connect(self.toggle_current_favorite)

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setProperty("class", "ctrl-btn")
        self.btn_fullscreen.setToolTip("Alternar Tela Cheia (F)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)

        ctrl_bar_layout.addWidget(self.btn_prev)
        ctrl_bar_layout.addWidget(self.btn_play_pause)
        ctrl_bar_layout.addWidget(self.btn_next)
        ctrl_bar_layout.addWidget(self.btn_recall)
        ctrl_bar_layout.addWidget(self.btn_reload)
        ctrl_bar_layout.addWidget(self.btn_guide_quick)
        ctrl_bar_layout.addWidget(self.btn_av_settings)
        ctrl_bar_layout.addWidget(self.btn_audio_mode_quick)
        ctrl_bar_layout.addWidget(self.btn_video_mode_quick)
        ctrl_bar_layout.addWidget(self.btn_pip)
        ctrl_bar_layout.addWidget(self.btn_diag)
        ctrl_bar_layout.addWidget(self.btn_fav)
        ctrl_bar_layout.addWidget(self.btn_fullscreen)
        ctrl_col.addLayout(ctrl_bar_layout)

        # Volume
        vol_layout = QHBoxLayout()
        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setFixedWidth(36)
        self.btn_mute.setProperty("class", "ctrl-btn")
        self.btn_mute.setToolTip("Silenciar áudio (M)")
        self.btn_mute.clicked.connect(self.toggle_mute)
        
        self.vol_slider = QSlider(QtCore.Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 200)
        self.vol_slider.setValue(self.current_volume)
        self.vol_slider.valueChanged.connect(self.set_volume_manual)
        
        self.vol_label = QLabel(f"{self.current_volume}%")
        self.vol_label.setFixedWidth(56)

        vol_layout.addWidget(self.btn_mute)
        vol_layout.addWidget(self.vol_slider)
        vol_layout.addWidget(self.vol_label)
        ctrl_col.addLayout(vol_layout)

        self.epg_info = QLabel("Atalhos: [G] Guia EPG | [O] Otimizador A/V | [V] Imagem | [A] Som | [I] Info OSD | [P] PiP | [Bksp] Recall | [F12] Diagnóstico | [F] Tela Cheia | [Espaço] Pausar")
        self.epg_info.setStyleSheet("color: #64748b; font-size: 11px;")
        ctrl_col.addWidget(self.epg_info)

        epg_main_layout.addLayout(ctrl_col, stretch=2)

        # Coluna 2: Guia Rápido EPG (Programa Atual e O Que Vem a Seguir)
        guide_col = QVBoxLayout()
        guide_col.setSpacing(6)

        guide_header = QHBoxLayout()
        guide_lbl_title = QLabel("📺 PROGRAMAÇÃO AO VIVO")
        guide_lbl_title.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 12px; letter-spacing: 0.5px;")
        guide_header.addWidget(guide_lbl_title)
        guide_header.addStretch()
        guide_col.addLayout(guide_header)

        # Programa Atual
        self.panel_prog_title = QLabel("Programa Atual...")
        self.panel_prog_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.panel_prog_title.setStyleSheet("color: #ffffff;")
        guide_col.addWidget(self.panel_prog_title)

        panel_prog_meta = QHBoxLayout()
        self.panel_prog_time = QLabel("00:00 - 00:00")
        self.panel_prog_time.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px;")

        self.panel_prog_rem = QLabel("Faltam 0 min")
        self.panel_prog_rem.setStyleSheet("color: #94a3b8; font-size: 11px;")

        panel_prog_meta.addWidget(self.panel_prog_time)
        panel_prog_meta.addStretch()
        panel_prog_meta.addWidget(self.panel_prog_rem)
        guide_col.addLayout(panel_prog_meta)

        self.panel_prog_bar = QProgressBar()
        self.panel_prog_bar.setRange(0, 100)
        self.panel_prog_bar.setValue(50)
        self.panel_prog_bar.setTextVisible(False)
        self.panel_prog_bar.setFixedHeight(5)
        self.panel_prog_bar.setStyleSheet("""
            QProgressBar { background-color: #1e293b; border-radius: 2px; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38bdf8, stop:1 #2563eb); border-radius: 2px; }
        """)
        guide_col.addWidget(self.panel_prog_bar)

        # Próximas Atrações
        self.panel_next_label = QLabel("⏭️ A Seguir: Próximo programa")
        self.panel_next_label.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        guide_col.addWidget(self.panel_next_label)

        epg_main_layout.addLayout(guide_col, stretch=3)

        self.right_layout.addWidget(self.epg_panel, stretch=1)
        self.content_layout.addWidget(self.right_panel)

        self.stack.addWidget(self.iptv_widget)

        # TELA 1: NAVEGADOR WEB (YOUTUBE, PLUTO TV, GLOBOPLAY, STREAMINGS)
        self.web_container = QWidget()
        web_layout = QVBoxLayout(self.web_container)
        web_layout.setContentsMargins(10, 10, 10, 10)
        web_layout.setSpacing(8)

        self.web_control_bar = QFrame()
        self.web_control_bar.setObjectName("web_control_bar")
        web_bar_layout = QHBoxLayout(self.web_control_bar)
        web_bar_layout.setContentsMargins(10, 6, 10, 6)

        btn_back_tv = QPushButton("📺 Voltar para TV Ao Vivo")
        btn_back_tv.setProperty("class", "accent-btn")
        btn_back_tv.clicked.connect(self.open_tv_mode)

        btn_fav_yt = QPushButton("⭐ Salvar Vídeo")
        btn_fav_yt.setProperty("class", "ctrl-btn")
        btn_fav_yt.clicked.connect(self.add_youtube_favorite)

        self.yt_fav_combo = QComboBox()
        self.yt_fav_combo.setMaxVisibleItems(8)
        self.yt_fav_combo.addItem("📋 Minha Lista de Vídeos Salvos")
        
        for fav in self.youtube_favs:
            self.yt_fav_combo.addItem(f"▶️ {fav['title'][:32]}...")

        self.yt_fav_combo.currentIndexChanged.connect(self.load_selected_yt_favorite)

        btn_remove_yt = QPushButton("🗑️ Remover Vídeo")
        btn_remove_yt.setProperty("class", "ctrl-btn")
        btn_remove_yt.clicked.connect(self.remove_youtube_favorite)

        web_bar_layout.addWidget(btn_back_tv)
        web_bar_layout.addWidget(btn_fav_yt)
        web_bar_layout.addWidget(self.yt_fav_combo)
        web_bar_layout.addWidget(btn_remove_yt)
        web_bar_layout.addStretch()

        web_layout.addWidget(self.web_control_bar)

        self.web_view = QWebEngineView()
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        self.web_view.page().fullScreenRequested.connect(self.handle_web_fullscreen)

        profile = QWebEngineProfile.defaultProfile()
        profile.setHttpUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        web_layout.addWidget(self.web_view)
        self.stack.addWidget(self.web_container)

    def handle_web_fullscreen(self, request):
        request.accept()
        if request.toggleOn():
            self.sidebar.hide()
            self.web_control_bar.hide()
            self.showFullScreen()
        else:
            self.sidebar.show()
            self.web_control_bar.show()
            self.showMaximized()

    def add_youtube_favorite(self):
        curr_url = self.web_view.url().toString()
        curr_title = self.web_view.title() or "Vídeo Salvo"
        if "youtube.com/watch" in curr_url or "youtu.be" in curr_url or "pluto.tv" in curr_url:
            self.youtube_favs.append({'title': curr_title, 'url': curr_url})
            self.yt_fav_combo.addItem(f"▶️ {curr_title[:32]}...")
            self.save_settings()
            QMessageBox.information(self, "Vídeo Salvo", f"'{curr_title}' foi adicionado aos seus favoritos!")

    def remove_youtube_favorite(self):
        idx = self.yt_fav_combo.currentIndex()
        if idx > 0:
            removed = self.youtube_favs.pop(idx - 1)
            self.yt_fav_combo.removeItem(idx)
            self.save_settings()
            QMessageBox.information(self, "Vídeo Removido", f"'{removed['title']}' foi removido com sucesso!")

    def load_selected_yt_favorite(self, index):
        if index > 0 and index - 1 < len(self.youtube_favs):
            fav = self.youtube_favs[index - 1]
            self.web_view.setUrl(QtCore.QUrl(fav['url']))

    def open_tv_mode(self):
        self.stack.setCurrentIndex(0)
        # Se estiver em PiP, restaura o vídeo para o quadro principal
        if self.is_pip_active:
            self.disable_pip_mode()
        if hasattr(self, 'mediaplayer') and not self.mediaplayer.is_playing():
            self.play_channel_by_index(self.current_channel_index)

    def open_tv_guide(self):
        guide = TVGuideDialog(self.all_channels, self.current_channel_index, self.play_channel_by_index, self)
        guide.exec()

    def open_web_app(self, url):
        """Abre aplicativos da Web. Se PiP estiver ativado, mantém o stream rodando na mini-janela."""
        if not self.is_pip_active:
            self.safe_vlc_call(self.mediaplayer.stop)
            self.is_playing = False
        else:
            logger.info("Navegando em Web App mantendo transmissão ativa no modo Picture-in-Picture.")

        self.web_view.setUrl(QtCore.QUrl(url))
        self.stack.setCurrentIndex(1)

    def prompt_add_custom_channel(self):
        name, ok1 = QInputDialog.getText(self, "Adicionar Canal", "Nome do Canal:")
        if ok1 and name.strip():
            url, ok2 = QInputDialog.getText(self, "Adicionar Canal", "URL do Stream (.m3u8):")
            if ok2 and url.strip():
                new_ch = {
                    'name': name.strip(),
                    'url': url.strip(),
                    'fallback_urls': [],
                    'group': 'Personalizados',
                    'badge': 'CUSTOM'
                }
                self.custom_channels.append(new_ch)
                self.all_channels.append(new_ch)
                self.categories.add('Personalizados')
                self.save_settings()
                self.populate_categories_and_channels()
                self.play_channel_by_index(len(self.all_channels) - 1)
                QMessageBox.information(self, "Canal Adicionado", f"O canal '{name}' foi adicionado com sucesso!")

    def populate_categories_and_channels(self):
        curr_cat = self.category_combo.currentText() if self.category_combo.count() > 0 else "Todas as Categorias"
        
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("Todas as Categorias")
        self.category_combo.addItem("⭐ Favoritos")
        self.category_combo.addItem("📺 TV Aberta Brasil")
        
        other_categories = sorted([c for c in self.categories if c != "TV Aberta Brasil"])
        for cat in other_categories:
            self.category_combo.addItem(cat)
            
        index = self.category_combo.findText(curr_cat)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        self.category_combo.blockSignals(False)

        self.filter_channels()

    def start_m3u_download(self, url):
        logger.info(f"Disparando thread M3UDownloader para URL: {url}")
        self.downloader = M3UDownloader(url)
        self.downloader.finished_signal.connect(self.on_m3u_loaded)
        self.downloader.start()

    def on_m3u_loaded(self, m3u_channels, m3u_categories):
        existing_urls = {c['url'] for c in self.all_channels}
        added_count = 0
        for ch in m3u_channels:
            if ch['url'] not in existing_urls:
                self.all_channels.append(ch)
                existing_urls.add(ch['url'])
                added_count += 1
                
        self.categories.update(m3u_categories)
        self.populate_categories_and_channels()
        logger.info(f"M3U processado: {added_count} novos canais adicionados à lista.")

    def filter_channels(self):
        search_query = remove_accents(self.search_bar.text().strip())
        selected_category = self.category_combo.currentText()

        self.channel_grid.clear()
        matched_count = 0

        for idx, channel in enumerate(self.all_channels):
            channel_name_clean = remove_accents(channel['name'])
            match_search = (search_query in channel_name_clean) if search_query else True
            is_favorite = channel['url'] in self.favorites_urls

            if selected_category == "⭐ Favoritos":
                match_category = is_favorite
            elif selected_category == "Todas as Categorias" or selected_category == "":
                match_category = True
            elif selected_category == "📺 TV Aberta Brasil":
                match_category = (channel.get('group') == 'TV Aberta Brasil')
            else:
                match_category = (channel.get('group') == selected_category)

            if match_search and match_category:
                matched_count += 1
                prefix = "⭐ " if is_favorite else "📺 "
                ch_number_str = f"{idx + 1:02d}. "
                item = QListWidgetItem(f"{ch_number_str}{prefix}{channel['name']}")
                item.setData(QtCore.Qt.ItemDataRole.UserRole, idx)
                self.channel_grid.addItem(item)

        self.lbl_channel_count.setText(f"Exibindo {matched_count} canal(is)")

    def play_channel_by_item(self, item):
        index = item.data(QtCore.Qt.ItemDataRole.UserRole)
        self.play_channel_by_index(index)

    def play_channel_by_index(self, index, url_attempt=0, silent_healing=False):
        if 0 <= index < len(self.all_channels):
            # Histórico de zapping para o botão Recall
            if index != self.current_channel_index and not silent_healing:
                if not self.zapping_history or self.zapping_history[-1] != self.current_channel_index:
                    self.zapping_history.append(self.current_channel_index)

            self.current_channel_index = index
            channel_data = self.all_channels[index]
            self.current_url_attempt = url_attempt
            self.stream_start_timestamp = time.time()
            self.last_playback_progress_timestamp = time.time()
            self.consecutive_freeze_seconds = 0

            urls_list = [channel_data['url']] + channel_data.get('fallback_urls', [])
            if url_attempt >= len(urls_list):
                url_attempt = 0
            
            target_url = urls_list[url_attempt]

            if url_attempt > 0:
                if silent_healing:
                    self.status_badge.setText(f"🔄 Auto-Healing ({url_attempt})...")
                else:
                    self.status_badge.setText(f"🔄 Servidor Reserva {url_attempt}...")
                self.status_badge.setStyleSheet("color: #facc15; font-weight: bold; font-size: 12px;")
            else:
                self.status_badge.setText("🟡 Conectando...")
                self.status_badge.setStyleSheet("color: #facc15; font-weight: bold; font-size: 12px;")

            self.safe_vlc_call(self.mediaplayer.stop)

            media = self.safe_vlc_call(self.instance.media_new, target_url)
            if not media:
                logger.error(f"Não foi possível instanciar media para URL: {target_url}")
                return
            
            # Buffer dinâmico adaptativo (800ms estável ou até 3000ms sob oscilação)
            media.add_option(f":network-caching={self.current_buffer_ms}")
            media.add_option(f":live-caching={self.current_buffer_ms}")
            media.add_option(":http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            
            # Otimização dinâmica de volume e imagem para o canal atual
            if getattr(self, 'audio_normalizer_enabled', True):
                media.add_option(":audio-filter=normvol")
                media.add_option(f":norm-max-level={getattr(self, 'audio_max_level', 2.5)}")
                media.add_option(":norm-buff-size=10")

            if getattr(self, 'video_deinterlace_enabled', True):
                media.add_option(":deinterlace=1")
                media.add_option(":deinterlace-mode=yadif2x")
            
            self.safe_vlc_call(self.mediaplayer.set_media, media)

            # Destino do vídeo: Janela PiP ou Tela Principal
            if getattr(self, 'is_pip_active', False) and hasattr(self, 'pip_window'):
                target_win_id = int(self.pip_window.video_surface.winId())
                self.pip_window.set_channel_name(channel_data['name'])
            else:
                target_win_id = int(self.video_frame.winId())

            if sys.platform == "win32":
                self.safe_vlc_call(self.mediaplayer.set_hwnd, target_win_id)
            elif sys.platform.startswith("linux"):
                self.safe_vlc_call(self.mediaplayer.set_xwindow, target_win_id)
            elif sys.platform == "darwin":
                self.safe_vlc_call(self.mediaplayer.set_nsobject, target_win_id)

            self.safe_vlc_call(self.mediaplayer.play)
            self.is_playing = True
            self.btn_play_pause.setText("⏸️ Pausar")

            QtCore.QTimer.singleShot(60, lambda: self.safe_vlc_call(self.mediaplayer.audio_set_volume, self.current_volume))
            QtCore.QTimer.singleShot(80, self.apply_audio_enhancements)
            QtCore.QTimer.singleShot(150, self.apply_video_enhancements)
            
            is_fav = channel_data['url'] in self.favorites_urls
            fav_icon = "⭐ " if is_fav else ""
            self.epg_title.setText(f"🔴 AO VIVO: {fav_icon}{channel_data['name']}")
            self.btn_fav.setText("⭐ Desfavoritar" if is_fav else "⭐ Favoritar")

            badge = channel_data.get('badge', '1080p • AO VIVO')
            if not silent_healing:
                self.show_tv_infobar(index + 1, channel_data['name'], channel_data.get('group', 'TV Aberta'), badge)
            self.update_epg_ui(channel_data)

            logger.info(
                f"Sintonizado canal CH {index+1:02d}: '{channel_data['name']}' "
                f"(Tentativa {url_attempt}, buffer {self.current_buffer_ms}ms, PiP: {self.is_pip_active})"
            )

    def recall_last_channel(self):
        """Alterna rapidamente entre o canal atual e o canal anterior (Zapping History / Recall)."""
        if not self.zapping_history:
            logger.info("Recall solicitado, porém o histórico de zapping está vazio.")
            return

        prev_idx = self.zapping_history.pop()
        if 0 <= prev_idx < len(self.all_channels):
            curr_idx = self.current_channel_index
            logger.info(f"Botão Recall acionado: alternando de CH {curr_idx+1:02d} para CH {prev_idx+1:02d} ({self.all_channels[prev_idx]['name']})")
            self.play_channel_by_index(prev_idx)
            # Permite alternância rápida "ping-pong" mantendo o canal de onde veio no histórico
            self.zapping_history.append(curr_idx)

    def update_epg_ui(self, channel_data):
        """Atualiza a programação da TV no painel e na barra OSD."""
        curr_info, upcoming_info, _ = EPGManager.get_current_and_upcoming(
            channel_data['name'],
            channel_data.get('group', 'Geral')
        )

        self.tv_ch_quick_tag.setText(f"CH {self.current_channel_index+1:02d} • {channel_data['name']}")

        self.panel_prog_title.setText(f"🔴 {curr_info['title']}")
        self.panel_prog_time.setText(f"🕒 {curr_info['time_range']}")
        self.panel_prog_rem.setText(curr_info['remaining'])
        self.panel_prog_bar.setValue(curr_info['progress'])

        if upcoming_info:
            next1 = upcoming_info[0]
            next_txt = f"⏭️ A Seguir: {next1['start']} - {next1['title']}"
            if len(upcoming_info) > 1:
                next2 = upcoming_info[1]
                next_txt += f"  |  {next2['start']} - {next2['title']}"
            self.panel_next_label.setText(next_txt)

        self.lbl_osd_current_prog.setText(f"🔴 NO AR AGORA: {curr_info['title']} ({curr_info['time_range']})")
        self.lbl_osd_remaining.setText(f"{curr_info['progress']}% • {curr_info['remaining']}")
        self.osd_progress_bar.setValue(curr_info['progress'])
        if upcoming_info:
            self.lbl_osd_next_prog.setText(f"⏭️ A SEGUIR: {upcoming_info[0]['start']} - {upcoming_info[0]['title']}")

    def show_tv_infobar(self, ch_num, title, category, badge="1080p • AO VIVO"):
        self.fade_animation.stop()
        self.overlay_timer.stop()

        self.lbl_ch_num.setText(f"CH {ch_num:03d}")
        self.lbl_ch_title.setText(title)
        self.lbl_ch_cat.setText(f"{category} • Transmissão Digital")
        self.lbl_ch_badge.setText(badge)
        
        if hasattr(self, 'lbl_enhancement_badge'):
            a_txt = "🔊 ÁUDIO NIVELADO" if getattr(self, 'audio_normalizer_enabled', True) else "ÁUDIO ORIGINAL"
            v_mode = getattr(self, 'video_mode', 'vivid')
            v_txt = "✨ SMART 16:9" if v_mode == 'vivid' else "🎬 CINEMA" if v_mode == 'cinema' else "📻 4:3"
            self.lbl_enhancement_badge.setText(f"{a_txt}  •  {v_txt}")

        self.opacity_effect.setOpacity(1.0)
        self.tv_infobar.show()

    def on_vlc_playing(self):
        self.status_badge.setText("🟢 Ao Vivo")
        self.status_badge.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 12px;")
        self.apply_audio_enhancements()
        self.apply_video_enhancements()
        self.last_playback_progress_timestamp = time.time()
        self.consecutive_freeze_seconds = 0
        self.auto_healing_in_progress = False
        self.auto_heal_attempts_on_channel = 0
        if self.tv_infobar.isVisible():
            self.overlay_timer.start(4000)
        logger.info(f"LibVLC reproduzindo com sucesso canal '{self.all_channels[self.current_channel_index]['name']}'")

    def on_vlc_buffering(self, cache_percent):
        now = time.time()
        if cache_percent < 100:
            self.status_badge.setText(f"🟡 Buffer: {cache_percent}%")
            self.status_badge.setStyleSheet("color: #facc15; font-weight: bold; font-size: 12px;")
            self.recent_buffering_timestamps.append(now)

            # Avalia instabilidade da rede: se houver 2 ou mais eventos de buffering nos últimos 15s
            recent_count = sum(1 for t in self.recent_buffering_timestamps if (now - t) <= 15.0)
            if recent_count >= 2 and self.current_buffer_ms < 3000:
                self.current_buffer_ms = 3000
                self.last_buffer_adapt_timestamp = now
                logger.warning(
                    f"Oscilação de rede detectada ({recent_count} quedas de buffer em 15s). "
                    f"Elevando temporariamente buffer VLC para {self.current_buffer_ms}ms para prevenir travamentos."
                )
        else:
            self.status_badge.setText("🟢 Ao Vivo")
            self.status_badge.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 12px;")
            self.last_playback_progress_timestamp = now
            self.consecutive_freeze_seconds = 0

    def on_vlc_error(self):
        logger.warning(f"VLC reportou erro na reprodução do canal index {self.current_channel_index}. Disparando cura automática...")
        self.trigger_auto_healing(reason="Erro nativo de decodificação LibVLC")

    def stream_watchdog_check(self):
        """
        Monitora ativamente a reprodução em tempo real (Watchdog de Resiliência).
        Se o stream cair ou congelar por mais de 4 segundos, dispara a cura automática
        (Auto-Healing) alternando para a próxima fallback_url de forma transparente.
        """
        if not getattr(self, 'is_playing', False):
            return

        now = time.time()

        # Proteção defensiva de chamadas LibVLC
        state = self.safe_vlc_call(self.mediaplayer.get_state, default=None)
        is_active = self.safe_vlc_call(self.mediaplayer.is_playing, default=0)
        curr_time = self.safe_vlc_call(self.mediaplayer.get_time, default=-1)

        # Checa se o stream está em reprodução ativa com progresso de frames/tempo
        is_advancing = False
        if state == vlc.State.Playing and is_active:
            if curr_time > 0 and curr_time != self.last_media_time:
                self.last_media_time = curr_time
                is_advancing = True
            elif curr_time == 0 or curr_time == -1:
                # Streams de TV aberta ao vivo (Live HLS) podem retornar time 0 ou -1
                time_since_buff = now - (self.recent_buffering_timestamps[-1] if self.recent_buffering_timestamps else 0)
                if time_since_buff > 1.5:
                    is_advancing = True

        if is_advancing:
            self.last_playback_progress_timestamp = now
            self.consecutive_freeze_seconds = 0
            self.auto_healing_in_progress = False

            # Avalia estabilidade prolongada para restaurar buffer de baixa latência (800ms)
            if self.current_buffer_ms > 800:
                time_since_last_buff = now - (self.recent_buffering_timestamps[-1] if self.recent_buffering_timestamps else self.last_buffer_adapt_timestamp)
                if time_since_last_buff >= 20.0:
                    self.current_buffer_ms = 800
                    logger.info(
                        f"Conexão estabilizada por >20s. Reduzindo buffer VLC para {self.current_buffer_ms}ms "
                        f"para minimizar latência do sinal ao vivo."
                    )
        else:
            # Detecta congelamento, travamento ou queda de sinal
            self.consecutive_freeze_seconds = now - self.last_playback_progress_timestamp

            if self.consecutive_freeze_seconds >= 4.0:
                logger.warning(
                    f"Watchdog: Stream congelado/parado por {self.consecutive_freeze_seconds:.1f}s "
                    f"(estado LibVLC: {state}, is_playing: {is_active}). Disparando Auto-Healing..."
                )
                self.trigger_auto_healing(reason="Congelamento de vídeo (>4s)")

    def trigger_auto_healing(self, reason="Falha no stream"):
        """
        Mecanismo de Auto-Healing em Tempo Real.
        Alterna silenciosamente para o próximo servidor de backup (fallback_url)
        sem exibir tela de erro imediata ao usuário.
        """
        if getattr(self, 'auto_healing_in_progress', False):
            return

        self.auto_healing_in_progress = True
        self.auto_heal_counter += 1

        if not (0 <= self.current_channel_index < len(self.all_channels)):
            self.auto_healing_in_progress = False
            return

        channel_data = self.all_channels[self.current_channel_index]
        urls_list = [channel_data['url']] + channel_data.get('fallback_urls', [])

        next_attempt = self.current_url_attempt + 1
        if next_attempt < len(urls_list):
            logger.warning(
                f"[Auto-Healing] Motivo: {reason}. "
                f"Canal '{channel_data['name']}': alternando transparentemente para fallback {next_attempt} "
                f"({urls_list[next_attempt]})."
            )
            # Eleva temporariamente o buffer para 3000ms para estabilizar a nova conexão
            self.current_buffer_ms = 3000
            self.status_badge.setText(f"🔄 Sincronizando (Backup {next_attempt})...")
            self.status_badge.setStyleSheet("color: #facc15; font-weight: bold; font-size: 12px;")

            self.play_channel_by_index(self.current_channel_index, url_attempt=next_attempt, silent_healing=True)
            self.last_playback_progress_timestamp = time.time()
            self.consecutive_freeze_seconds = 0
        else:
            # Fallbacks esgotados: tenta uma reconexão primária com buffer de 3000ms antes de desistir
            if self.auto_heal_attempts_on_channel < 2:
                self.auto_heal_attempts_on_channel += 1
                logger.warning(
                    f"[Auto-Healing] Fallbacks esgotados no canal '{channel_data['name']}'. "
                    f"Tentativa de reconexão nº {self.auto_heal_attempts_on_channel} com buffer de 3000ms..."
                )
                self.current_buffer_ms = 3000
                self.play_channel_by_index(self.current_channel_index, url_attempt=0, silent_healing=True)
                self.last_playback_progress_timestamp = time.time()
                self.consecutive_freeze_seconds = 0
            else:
                # Esgotou tentativas: agora e somente agora exibe aviso de sem sinal
                logger.error(
                    f"[Auto-Healing] Todas as alternativas falharam no canal '{channel_data['name']}'. "
                    f"Exibindo aviso de ausência de sinal."
                )
                self.status_badge.setText("🔴 Sem Sinal")
                self.status_badge.setStyleSheet("color: #f87171; font-weight: bold; font-size: 12px;")
                self.show_tv_infobar(
                    self.current_channel_index + 1,
                    channel_data['name'],
                    "Transmissão Indisponível",
                    "RECONECTAR [R]"
                )
                self.auto_healing_in_progress = False

    def toggle_pip_mode(self):
        """Alterna entre o modo de vídeo na janela principal e Picture-in-Picture (PiP)."""
        if self.is_pip_active:
            self.disable_pip_mode()
        else:
            self.enable_pip_mode()

    def enable_pip_mode(self):
        """Destaca o vídeo em uma mini-janela flutuante no canto da tela."""
        if self.is_pip_active:
            return

        self.is_pip_active = True
        channel_name = self.all_channels[self.current_channel_index]['name'] if self.all_channels else "TV Ao Vivo"
        self.pip_window.set_channel_name(channel_name)

        screen_geo = QApplication.primaryScreen().availableGeometry()
        pip_w, pip_h = self.pip_window.width(), self.pip_window.height()
        self.pip_window.move(screen_geo.right() - pip_w - 24, screen_geo.bottom() - pip_h - 24)
        self.pip_window.show()

        pip_win_id = int(self.pip_window.video_surface.winId())
        if sys.platform == "win32":
            self.safe_vlc_call(self.mediaplayer.set_hwnd, pip_win_id)
        elif sys.platform.startswith("linux"):
            self.safe_vlc_call(self.mediaplayer.set_xwindow, pip_win_id)
        elif sys.platform == "darwin":
            self.safe_vlc_call(self.mediaplayer.set_nsobject, pip_win_id)

        self.pip_active_banner.show()
        self.btn_pip.setText("🖼️ Fechar PiP")
        logger.info(f"Modo Picture-in-Picture ativado para o canal '{channel_name}'.")

    def disable_pip_mode(self):
        """Restaura o vídeo de volta para a janela principal."""
        if not self.is_pip_active:
            return

        self.is_pip_active = False
        self.pip_window.hide()
        self.pip_active_banner.hide()
        self.btn_pip.setText("🖼️ PiP")

        main_win_id = int(self.video_frame.winId())
        if sys.platform == "win32":
            self.safe_vlc_call(self.mediaplayer.set_hwnd, main_win_id)
        elif sys.platform.startswith("linux"):
            self.safe_vlc_call(self.mediaplayer.set_xwindow, main_win_id)
        elif sys.platform == "darwin":
            self.safe_vlc_call(self.mediaplayer.set_nsobject, main_win_id)

        logger.info("Modo Picture-in-Picture desativado. Vídeo retornado à janela principal.")

    def open_diagnostic_dialog(self):
        """Abre o Painel de Diagnóstico e Telemetria em Tempo Real (F12)."""
        logger.info("Abrindo Painel de Diagnóstico em Tempo Real...")
        diag = DiagnosticDialog(self, self)
        diag.exec()

    def apply_audio_enhancements(self):
        """Aplica nivelamento inteligente de áudio e pré-amplificação com proteção defensiva."""
        try:
            if not hasattr(self, 'mediaplayer') or not self.mediaplayer:
                return
            if getattr(self, 'audio_normalizer_enabled', True):
                eq = self.safe_vlc_call(vlc.libvlc_audio_equalizer_new)
                if eq:
                    preamp = float(getattr(self, 'audio_preamp', 6.0))
                    self.safe_vlc_call(vlc.libvlc_audio_equalizer_set_preamp, eq, preamp)
                    
                    a_mode = getattr(self, 'audio_mode', 'smart')
                    if a_mode == "dialogue":
                        self.safe_vlc_call(vlc.libvlc_audio_equalizer_set_amp_at_index, eq, 2.0, 4) # 500 Hz
                        self.safe_vlc_call(vlc.libvlc_audio_equalizer_set_amp_at_index, eq, 5.0, 5) # 1000 Hz
                        self.safe_vlc_call(vlc.libvlc_audio_equalizer_set_amp_at_index, eq, 6.0, 6) # 2000 Hz
                        self.safe_vlc_call(vlc.libvlc_audio_equalizer_set_amp_at_index, eq, 4.0, 7) # 4000 Hz
                        
                    self.safe_vlc_call(self.mediaplayer.set_equalizer, eq)
                    self.current_eq = eq
            else:
                self.safe_vlc_call(self.mediaplayer.set_equalizer, None)
                self.current_eq = None
        except Exception as e:
            logger.error(f"Erro ao equalizar áudio: {e}", exc_info=True)

    def apply_video_enhancements(self):
        """Aplica desentrelaçamento 60fps e proporção de tela Smart TV sem travar o vídeo."""
        try:
            if not hasattr(self, 'mediaplayer') or not self.mediaplayer:
                return
            if getattr(self, 'video_deinterlace_enabled', True):
                self.safe_vlc_call(self.mediaplayer.video_set_deinterlace, b'yadif2x')
            else:
                self.safe_vlc_call(self.mediaplayer.video_set_deinterlace, b'disable')

            v_mode = getattr(self, 'video_mode', 'vivid')
            if v_mode == 'vivid':
                self.safe_vlc_call(self.mediaplayer.video_set_aspect_ratio, b'16:9')
            elif v_mode == '4:3':
                self.safe_vlc_call(self.mediaplayer.video_set_aspect_ratio, b'4:3')
            else:
                self.safe_vlc_call(self.mediaplayer.video_set_aspect_ratio, None)
        except Exception as e:
            logger.error(f"Erro ao otimizar vídeo: {e}", exc_info=True)

    def open_av_settings_dialog(self):
        """Abre o diálogo de calibração de imagem e som Smart TV."""
        dlg = AVSettingsDialog(self)
        dlg.exec()

    def cycle_picture_mode(self):
        modes = ["vivid", "cinema", "4:3"]
        curr = getattr(self, 'video_mode', 'vivid')
        nxt = modes[(modes.index(curr) + 1) % len(modes)] if curr in modes else "vivid"
        self.video_mode = nxt
        self.apply_video_enhancements()
        self.save_settings()
        
        lbl = "✨ SMART 16:9 (VÍVIDO)" if nxt == "vivid" else "🎬 MODO CINEMA" if nxt == "cinema" else "📻 CLÁSSICO 4:3"
        self.btn_video_mode_quick.setText("✨ Vívido" if nxt == "vivid" else "🎬 Cinema" if nxt == "cinema" else "📻 4:3")
        ch_data = self.all_channels[self.current_channel_index]
        self.show_tv_infobar(self.current_channel_index + 1, ch_data['name'], ch_data.get('group', 'TV Aberta'), lbl)
        self.overlay_timer.start(3000)

    def cycle_audio_mode(self):
        if not getattr(self, 'audio_normalizer_enabled', True):
            self.audio_normalizer_enabled = True
            self.audio_mode = "smart"
            txt = "🔊 ÁUDIO NIVELADO (SMART)"
            self.btn_audio_mode_quick.setText("🔊 Nivelar")
        elif self.audio_mode == "smart":
            self.audio_mode = "dialogue"
            txt = "🗣️ CLAREZA DE VOZES (DIÁLOGO)"
            self.btn_audio_mode_quick.setText("🗣️ Vozes")
        else:
            self.audio_normalizer_enabled = False
            txt = "🔈 ÁUDIO ORIGINAL (DIRETO)"
            self.btn_audio_mode_quick.setText("🔈 Direto")

        self.apply_audio_enhancements()
        self.save_settings()
        ch_data = self.all_channels[self.current_channel_index]
        self.show_tv_infobar(self.current_channel_index + 1, ch_data['name'], ch_data.get('group', 'TV Aberta'), txt)
        self.overlay_timer.start(3000)

    def start_infobar_fadeout(self):
        self.fade_animation.start()

    def toggle_play_pause(self):
        if hasattr(self, 'mediaplayer'):
            if self.mediaplayer.is_playing():
                self.safe_vlc_call(self.mediaplayer.pause)
                self.is_playing = False
                self.btn_play_pause.setText("▶️ Reproduzir")
                self.status_badge.setText("⏸️ Pausado")
                self.status_badge.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 12px;")
            else:
                self.safe_vlc_call(self.mediaplayer.play)
                self.is_playing = True
                self.btn_play_pause.setText("⏸️ Pausar")
                self.status_badge.setText("🟢 Ao Vivo")
                self.status_badge.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 12px;")

    def reload_current_channel(self):
        logger.info(f"Recarregando canal atual: CH {self.current_channel_index+1:02d}")
        self.play_channel_by_index(self.current_channel_index, 0)

    def next_channel(self):
        if self.all_channels:
            next_idx = (self.current_channel_index + 1) % len(self.all_channels)
            self.play_channel_by_index(next_idx)

    def prev_channel(self):
        if self.all_channels:
            prev_idx = (self.current_channel_index - 1 + len(self.all_channels)) % len(self.all_channels)
            self.play_channel_by_index(prev_idx)

    def toggle_favorite_context(self, position):
        item = self.channel_grid.itemAt(position)
        if item:
            idx = item.data(QtCore.Qt.ItemDataRole.UserRole)
            self.toggle_favorite_by_index(idx)

    def toggle_current_favorite(self):
        self.toggle_favorite_by_index(self.current_channel_index)

    def toggle_favorite_by_index(self, index):
        if 0 <= index < len(self.all_channels):
            url = self.all_channels[index]['url']
            if url in self.favorites_urls:
                self.favorites_urls.remove(url)
            else:
                self.favorites_urls.add(url)
            
            self.save_settings()
            self.filter_channels()
            
            if index == self.current_channel_index:
                is_fav = url in self.favorites_urls
                prefix = "⭐ " if is_fav else ""
                self.epg_title.setText(f"🔴 AO VIVO: {prefix}{self.all_channels[index]['name']}")
                self.btn_fav.setText("⭐ Desfavoritar" if is_fav else "⭐ Favoritar")
                
                channel_data = self.all_channels[index]
                status = "REMOVIDO DOS FAVORITOS" if not is_fav else "SALVO NOS FAVORITOS"
                self.show_tv_infobar(index + 1, channel_data['name'], channel_data.get('group', 'TV Aberta'), status)
                self.overlay_timer.start(3500)

    def set_volume_manual(self, value):
        self.current_volume = value
        self.safe_vlc_call(self.mediaplayer.audio_set_volume, self.current_volume)
        self.vol_slider.setValue(self.current_volume)
        if self.current_volume > 100:
            self.vol_label.setText(f"{self.current_volume}% ⚡")
            self.vol_label.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 11px;")
        else:
            self.vol_label.setText(f"{self.current_volume}%")
            self.vol_label.setStyleSheet("color: #f1f5f9; font-size: 11px;")
        if self.current_volume == 0:
            self.btn_mute.setText("🔇")
        else:
            self.btn_mute.setText("🔊")
            self.is_muted = False
        self.save_settings()

    def toggle_mute(self):
        if self.is_muted:
            self.set_volume_manual(self.pre_mute_volume if self.pre_mute_volume > 0 else 50)
            self.is_muted = False
        else:
            self.pre_mute_volume = self.current_volume
            self.set_volume_manual(0)
            self.is_muted = True
            self.btn_mute.setText("🔇")

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.sidebar.hide()
            self.left_panel.hide()
            self.epg_panel.hide()
            self.content_layout.setContentsMargins(0, 0, 0, 0)
            self.video_frame.setStyleSheet("background-color: #000000; border-radius: 0px;")
            self.showFullScreen()
            channel_data = self.all_channels[self.current_channel_index]
            self.show_tv_infobar(self.current_channel_index + 1, channel_data['name'], channel_data.get('group', 'TV Aberta'))
            self.overlay_timer.start(4000)
        else:
            self.sidebar.show()
            self.left_panel.show()
            self.epg_panel.show()
            self.content_layout.setContentsMargins(14, 14, 14, 14)
            self.video_frame.setStyleSheet("background-color: #000000; border-radius: 14px;")
            self.showMaximized()

    def toggle_info_osd(self):
        """Alterna a exibição da barra de informações OSD."""
        if self.tv_infobar.isVisible():
            self.tv_infobar.hide()
            self.overlay_timer.stop()
        else:
            channel_data = self.all_channels[self.current_channel_index]
            self.show_tv_infobar(self.current_channel_index + 1, channel_data['name'], channel_data.get('group', 'TV Aberta'))
            self.update_epg_ui(channel_data)
            self.overlay_timer.start(5000)

    def commit_number_jump(self):
        if self.number_buffer:
            try:
                target_num = int(self.number_buffer)
                target_idx = target_num - 1
                if 0 <= target_idx < len(self.all_channels):
                    self.play_channel_by_index(target_idx)
            except ValueError:
                pass
            self.number_buffer = ""

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()

            # Tecla F ou F11: Alternar Tela Cheia
            if key in (QtCore.Qt.Key.Key_F, QtCore.Qt.Key.Key_F11):
                self.toggle_fullscreen()
                return True
            # Esc: Sair de Tela Cheia
            elif key == QtCore.Qt.Key.Key_Escape and self.is_fullscreen:
                self.toggle_fullscreen()
                return True
            # Tecla F12: Painel de Diagnóstico em Tempo Real
            elif key == QtCore.Qt.Key.Key_F12:
                self.open_diagnostic_dialog()
                return True
            # Tecla P: Alternar Picture-in-Picture (PiP)
            elif key == QtCore.Qt.Key.Key_P:
                self.toggle_pip_mode()
                return True
            # Tecla Backspace: Recall / Último Canal Assistido (Zapping History)
            elif key == QtCore.Qt.Key.Key_Backspace:
                self.recall_last_channel()
                return True

            # Atalhos de TV Box enquanto estiver no modo de TV e fora da barra de busca
            if hasattr(self, 'stack') and self.stack.currentIndex() == 0:
                is_searching = hasattr(self, 'search_bar') and self.search_bar.hasFocus()
                
                if not is_searching:
                    # Tecla G: Abrir Guia de Programação (EPG)
                    if key == QtCore.Qt.Key.Key_G:
                        self.open_tv_guide()
                        return True
                    # Tecla O: Abrir Central de Qualidade (Otimizador A/V)
                    elif key == QtCore.Qt.Key.Key_O:
                        self.open_av_settings_dialog()
                        return True
                    # Tecla V: Alternar Modo de Imagem Smart TV
                    elif key == QtCore.Qt.Key.Key_V:
                        self.cycle_picture_mode()
                        return True
                    # Tecla A: Alternar Modo de Áudio / Nivelador
                    elif key == QtCore.Qt.Key.Key_A:
                        self.cycle_audio_mode()
                        return True
                    # Tecla I: Alternar Informações OSD
                    elif key == QtCore.Qt.Key.Key_I:
                        self.toggle_info_osd()
                        return True
                    # Espaço: Play/Pause
                    elif key == QtCore.Qt.Key.Key_Space:
                        self.toggle_play_pause()
                        return True
                    # Tecla R: Recarregar
                    elif key == QtCore.Qt.Key.Key_R:
                        self.reload_current_channel()
                        return True
                    # Teclas Cima / PageUp: Canal Anterior
                    elif key in (QtCore.Qt.Key.Key_Up, QtCore.Qt.Key.Key_PageUp):
                        self.prev_channel()
                        return True
                    # Teclas Baixo / PageDown: Próximo Canal
                    elif key in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_PageDown):
                        self.next_channel()
                        return True
                    # Tecla M: Silenciar Áudio (Mute)
                    elif key == QtCore.Qt.Key.Key_M:
                        self.toggle_mute()
                        return True
                    # Volume: + ou = para aumentar, - ou _ para diminuir (+5% / -5%)
                    elif key in (QtCore.Qt.Key.Key_Plus, QtCore.Qt.Key.Key_Equal):
                        self.set_volume_manual(min(200, self.current_volume + 5))
                        return True
                    elif key in (QtCore.Qt.Key.Key_Minus, QtCore.Qt.Key.Key_Underscore):
                        self.set_volume_manual(max(0, self.current_volume - 5))
                        return True
                    # Digitação numérica de canal (0-9) para TV Box Remote Control
                    elif QtCore.Qt.Key.Key_0 <= key <= QtCore.Qt.Key.Key_9:
                        digit = str(key - QtCore.Qt.Key.Key_0)
                        self.number_buffer += digit
                        self.show_tv_infobar(
                            int(self.number_buffer),
                            f"Sintonizando canal {self.number_buffer}...",
                            "Seleção Numérica",
                            "SINTONIZANDO"
                        )
                        self.number_timer.start(1200)
                        return True

        # Duplo clique na tela de vídeo alterna tela cheia
        if hasattr(self, 'video_frame') and obj == self.video_frame and event.type() == QtCore.QEvent.Type.MouseButtonDblClick:
            self.toggle_fullscreen()
            return True

        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        logger.info("Encerrando TutuTV Box Brasil...")
        self.save_settings()
        if hasattr(self, 'stream_watchdog_timer'):
            self.stream_watchdog_timer.stop()
        if hasattr(self, 'clock_timer'):
            self.clock_timer.stop()
        if hasattr(self, 'pip_window'):
            self.pip_window.close()

        if hasattr(self, 'mediaplayer') and self.mediaplayer:
            try:
                self.event_manager.event_detach(vlc.EventType.MediaPlayerPlaying)
                self.event_manager.event_detach(vlc.EventType.MediaPlayerEncounteredError)
                self.event_manager.event_detach(vlc.EventType.MediaPlayerBuffering)
            except Exception as e:
                logger.debug(f"Erro ao desconectar eventos LibVLC: {e}")
            self.safe_vlc_call(self.mediaplayer.stop)

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    global_font = QFont("Segoe UI", 10)
    app.setFont(global_font)
    
    player = IPTVPlayerBR()
    player.showMaximized()
    sys.exit(app.exec())
