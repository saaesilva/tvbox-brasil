# 📺 TutuTV Box Brasil — Player Moderno de IPTV (PC & TV Box)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?style=flat-square&logo=qt)](https://riverbankcomputing.com/software/pyqt/)
[![LibVLC](https://img.shields.io/badge/Player-LibVLC-FF8800?style=flat-square&logo=vlc-media-player)](https://www.videolan.org/vlc/)
[![Plataforma](https://img.shields.io/badge/Plataforma-Windows_10_%2F_11-0078D6?style=flat-square&logo=windows)](https://microsoft.com)

> Player desktop de alta performance desenvolvido em **Python** e **PyQt6** integrado com o motor multimídia **LibVLC**, especialmente otimizado para reprodução estável de canais abertos do Brasil em computadores e aparelhos TV Box.

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

1. **Python 3.10 ou superior (64-bit)**
2. **VLC Media Player 64-bit** instalado no sistema:
   - O aplicativo localiza automaticamente a `libvlc.dll` no caminho padrão (`C:\Program Files\VideoLAN\VLC`).
   - Se o seu VLC for 64-bit, garanta que o Python também seja executado em versão 64-bit.

---

## 🚀 Como Executar

### 1. Clonar o Repositório
```bash
git clone https://github.com/saaesilva/tvbox-brasil.git
cd tvbox-brasil
```

### 2. Criar e Ativar Ambiente Virtual
```bash
# Criar ambiente virtual
python -m venv venv

# Ativar no Windows (PowerShell)
.\venv\Scripts\Activate.ps1
```

### 3. Instalar as Dependências
```bash
pip install -r requirements.txt
```

### 4. Iniciar a Aplicação
```bash
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

Desenvolvido por **[Samuel Silva](https://github.com/saaesilva)**.  
Projeto destinado para fins educacionais e uso pessoal. Todos os fluxos de transmissão pertencem às suas respectivas emissoras detentoras dos direitos de transmissão.
