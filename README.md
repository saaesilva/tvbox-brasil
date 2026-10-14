# 📺 TutuTV Box Brasil — Player Moderno de IPTV (PC & TV Box)

<p align="center">
  <img src="https://raw.githubusercontent.com/saaesilva/tvbox-brasil/main/docs/preview.jpg" alt="TutuTV Box Brasil - Interface e Picture-in-Picture" width="100%" />
</p>

<p align="center">
  <a href="https://github.com/saaesilva/tvbox-brasil/releases/latest">
    <img src="https://img.shields.io/badge/Download_Oficial_v1.0.0-Executável_.exe-brightgreen?style=for-the-badge&logo=windows" alt="Download Executável" />
  </a>
  <img src="https://img.shields.io/badge/Licença-MIT-blue?style=for-the-badge" alt="Licença MIT" />
</p>

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?style=flat-square&logo=qt)](https://riverbankcomputing.com/software/pyqt/)
[![LibVLC](https://img.shields.io/badge/Player-LibVLC-FF8800?style=flat-square&logo=vlc-media-player)](https://www.videolan.org/vlc/)
[![Releases](https://img.shields.io/github/v/release/saaesilva/tvbox-brasil?style=flat-square&color=success)](https://github.com/saaesilva/tvbox-brasil/releases)

> Player desktop de alta performance desenvolvido em **Python** e **PyQt6** integrado com o motor multimídia **LibVLC**, especialmente otimizado para reprodução estável de canais abertos do Brasil em computadores e aparelhos TV Box.

---

## ⚡ Download Rápido (Sem Instalar Python)

Você pode baixar a versão compilada e portátil diretamente na aba de **[Releases Oficiais](https://github.com/saaesilva/tvbox-brasil/releases/tag/v1.0.0)**:
👉 **[Baixar TutuTV-Box-Brasil-v1.0.0.exe](https://github.com/saaesilva/tvbox-brasil/releases/download/v1.0.0/TutuTV-Box-Brasil-v1.0.0.exe)**

---

## ✨ Principais Funcionalidades

- 📡 **Foco em Emissoras Abertas do Brasil**: Catálogo pré-organizado por categorias (Abertos, Notícias, Variedades, Esportes e Cultura).
- 🖼️ **Picture-in-Picture (PiP)**: Janela flutuante desacoplável e redimensionável para assistir programas enquanto utiliza outros aplicativos.
- 📅 **Guia de Programação (EPG)**: Consulta integrada da grade horária e informações de programas atuais e seguintes.
- 🔄 **Mecanismo de Auto-Healing**: Reconexão inteligente e watchdog de fluxo para recuperar transmissões instáveis (HLS/m3u8) sem intervenção do usuário.
- ⌨️ **Controle Remoto & Teclado Completo**:
  - Digitação numérica direta (`0-9`) para troca rápida de canal.
  - Teclas direcionais (`Cima` / `Baixo`) para navegação em grade.
  - Tecla `F` ou `F11` para alternar modo Tela Cheia sem bordas.
  - Tecla `P` para ativar/desativar modo Picture-in-Picture.
  - Tecla `Backspace` para função *Recall* (retornar ao último canal sintonizado).
  - Tecla `F12` para painel de diagnóstico e telemetria de rede.
- 🎛️ **Otimizador Audiovisual**:
  - Nivelador automático de volume para evitar picos desagradáveis.
  - Equalizador de áudio e modos de imagem predefinidos (Padrão, Cinema, Dinâmico).
  - Ajuste de proporção de aspecto (Aspect Ratio: 16:9, 4:3, Original).
- 📊 **Barra OSD Inteligente**: Exibe número do canal, logo, categoria, resolução, bitrate e buffering em tempo real.

---

## 🛠️ Requisitos do Sistema

1. **Windows 10 ou 11 (64-bit)**
2. **VLC Media Player 64-bit** instalado no sistema:
   - O aplicativo localiza automaticamente a `libvlc.dll` no caminho padrão (`C:\Program Files\VideoLAN\VLC`).
   - Se executar via código-fonte, garanta que a versão do Python seja 64-bit.

---

## 🚀 Como Executar pelo Código-Fonte

```bash
# 1. Clonar o repositório
git clone https://github.com/saaesilva/tvbox-brasil.git
cd tvbox-brasil

# 2. Criar e ativar ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Executar
python TVBox.py
```

---

## ⌨️ Tabela de Atalhos

| Tecla | Ação |
| :--- | :--- |
| `0 - 9` | Sintonizar diretamente pelo número do canal |
| `↑` / `↓` | Canal anterior / Próximo canal |
| `Espaço` | Reproduzir / Pausar |
| `F` ou `F11` | Alternar Tela Cheia |
| `P` | Alternar modo Picture-in-Picture (PiP) |
| `M` | Silenciar áudio (Mudo) |
| `+` / `-` | Aumentar / Diminuir volume |
| `Backspace` | Canal anterior assistido (Recall / Zapping) |
| `G` | Abrir Guia de Programação (EPG) |
| `O` | Abrir Central de Configurações A/V |
| `F12` | Painel de Diagnóstico em tempo real |
| `Esc` | Sair da tela cheia |

---

## 📄 Licença e Direitos

Distribuído sob a licença **MIT**. Veja o arquivo `LICENSE` para mais detalhes.  
Desenvolvido por **[Samuel Silva](https://github.com/saaesilva)**.
