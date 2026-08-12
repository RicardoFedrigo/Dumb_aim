# Fallow Me - Motion Control System

Um sistema de reconhecimento de movimentos corporais via webcam que simula comandos de teclado e mouse em tempo real. Ideal para jogos e aplicações que requerem controle natural baseado em gestos.

## Requisitos

- Python 3.13+
- Webcam funcional
- Ambiente virtual (venv) recomendado

## Instalação

### 1. Ativar o ambiente virtual

```bash
source venv/bin/activate  # Linux/macOS
# ou
venv\Scripts\activate  # Windows
```

### 2. Instalar dependências

```bash
pip install -r requirements.txt
```

## Uso

### Executar com simulação de teclado/mouse ativada (padrão)

```bash
python3.13 main.py
```

### Executar apenas visualizando movimentos (sem simular input)

```bash
python3.13 main.py --disable-input
```

### Forçar driver de input de uma plataforma específica

```bash
python3.13 main.py --platform linux   # opções: auto|linux|windows|mac
```

## Mapeamento de Movimentos

| Movimento | Detecção | Teclas Simuladas |
|-----------|----------|------------------|
| **Andando** | Oscilação leve do tronco | `w` |
| **Correndo** | Movimentação rápida do tronco | `shift` + `w` |
| **Agachado** | Aproximação entre ombros e quadril | `ctrl` |
| **Inclinado** | Inclinação dos ombros (esquerda/direita) | `e` / `q` |

## Modos de Mouse

O programa possui dois modos de controle de mouse, alternados com a tecla `M`:

### 1. Modo Alvo (padrão)

Segue um objeto vermelho/laranja visível pela webcam. O cursor é movido diretamente para a posição do objeto na tela (mapeamento linear câmera → tela).

### 2. Modo Vetorial (Vector Mouse)

Deriva relativa do mouse com **perspectiva de mira alternável em tempo real** (tecla `N`):

- **Perspectiva `CAMERA`** (padrão): usa a posição do **ponto vermelho/laranja** em relação ao centro de mira da webcam como joystick. O centro de mira pode ser **calibrado** com a tecla `C`: a posição atual do ponto vira a origem (neutro), então a deriva é medida a partir dela — permitindo mirar de qualquer ponto do frame (até da borda). Sem calibração, a origem é o centro do frame.
- **Perspectiva `SCREEN`**: usa a posição do **cursor** em relação ao centro da tela como joystick (quanto mais longe o cursor estiver do centro da tela, mais rápido o ponteiro deriva).

Em ambas:

- Quanto maior o deslocamento em relação ao centro, maior a aceleração de deriva (`moveRel`), em rampa controlada (`CURVE`) entre `MIN_SPEED` e `MAX_SPEED` px/frame.
- O deslocamento é **relativo** (`moveRel`), suavizado por média exponencial (`SMOOTHING`) e sem saltos, inclusive ao inverter a direção.
- Uma **zona morta circular** no centro (raio = `DEAD_ZONE` × meia-diagonal) segura o ponteiro parado: centralize o alvo (câmera) ou o cursor (tela) para frear.
- Quando o ponteiro atinge a **borda da tela ele fica preso** lá (não escapa); a caixa de captura fica vermelha e o rótulo mostra `BORDA` enquanto o cursor estiver colado na borda. Para voltar, reposicione o alvo/cursor para o centro (o ponteiro para) ou para o lado oposto (a deriva inverte).
- Fora da zona morta, uma **seta** parte do centro do frame apontando na direção da deriva, com comprimento e percentual (`Accel`) proporcionais à velocidade atual.
- Na perspectiva `CAMERA`, se o objeto vermelho sair da visão da câmera, a deriva desacelera até parar.

## Configuração

Você pode personalizar o mapeamento de teclas e os thresholds de sensibilidade editando a seção `CONFIG` no topo do arquivo `main.py`:

```python
CONFIG = {
    "KEY_MAP": {
        "WALK": ["w"],
        "RUN": ["shift", "w"],
        "CROUCH": ["ctrl"]
    },
    "THRESHOLDS": {
        "WALK": 0.015,             # Sensibilidade para andada
        "RUN": 0.045,              # Sensibilidade para corrida
        "CROUCH_RATIO": 0.15,      # Proporção para detectar agachamento
        "INCLINE_ANGLE_DEGREES": 30 # Ângulo mínimo para detectar inclinação
    },
    "VECTOR_MOUSE": {
        "TOGGLE_KEY": "m",         # Tecla para alternar entre os modos de mouse
        "AIM_KEY": "n",            # Tecla para alternar a perspectiva de mira (camera/screen)
        "CALIBRATE_KEY": "c",      # Tecla para calibrar o centro de mira no ponto vermelho atual
        "AIM_REFERENCE": "camera", # 'camera' = ponto vermelho no frame | 'screen' = cursor vs centro da tela
        "DEAD_ZONE": 0.06,         # Zona morta no centro do frame (fracao da meia-diagonal, 0 = desativada)
        "MIN_SPEED": 8,            # Velocidade minima de deriva (px/frame) fora da zona morta
        "MAX_SPEED": 60,           # Velocidade maxima de deriva (px/frame) com o ponto na borda do frame
        "CURVE": 1.5,              # Expoente da rampa (1.0 = linear, >1 = acelera na borda)
        "SMOOTHING": 0.15          # Suavizacao exponencial da velocidade (0 = instantaneo, 1 = muito lento)
    },
    "INPUT_ENABLED": True,
    "PAUSE_KEY": "p"          # Pausar/retomar a simulacao de teclado/mouse (P)
}
```

### Ajuste de Thresholds

- **WALK**: Aumentar valor = movimento maior necessário para andar
- **RUN**: Aumentar valor = movimento mais rápido necessário para correr
- **CROUCH_RATIO**: Aumentar valor = detecta agachamento mais profundo
- **INCLINE_ANGLE_DEGREES**: Aumentar valor = requer inclinação mais acentuada dos ombros
- **VECTOR_MOUSE.AIM_REFERENCE**: Perspectiva inicial da mira — `camera` (ponto vermelho vs centro de mira) ou `screen` (cursor vs centro da tela)
- **VECTOR_MOUSE.AIM_KEY**: Tecla para alternar a perspectiva de mira em tempo real (padrão `N`)
- **VECTOR_MOUSE.CALIBRATE_KEY**: Tecla para calibrar o centro de mira no ponto vermelho atual (padrão `C`; sem ponto, reseta para o centro do frame)
- **VECTOR_MOUSE.DEAD_ZONE**: Fração da meia-diagonal usada como raio circular no centro; dentro dela o mouse não deriva (`0` desativa)
- **VECTOR_MOUSE.MIN_SPEED**: Velocidade mínima de deriva logo após sair da zona morta (evita resposta "morta")
- **VECTOR_MOUSE.MAX_SPEED**: Velocidade máxima de deriva quando o alvo está na borda (limita a velocidade para controle previsível)
- **VECTOR_MOUSE.CURVE**: Expoente da rampa de velocidade (`1.0` linear; valores maiores concentram a aceleração perto da borda)
- **VECTOR_MOUSE.SMOOTHING**: Fator de suavização exponencial da velocidade (`0` = instantâneo; valores altos = mais lento/suave)

## Compatibilidade

- **Linux**: Suportado (requer `pydirectinput`)
- **macOS**: Suportado com `pyautogui` como fallback
- **Windows**: Suportado com `pydirectinput`

O programa tenta usar `pydirectinput` automaticamente e faz fallback para `pyautogui` se não disponível.

## Controles

| Tecla | Ação |
|-------|------|
| `M` | Alternar entre modo Alvo e modo Vetorial (Vector Mouse) |
| `N` | Alternar a perspectiva da mira vetorial: `CAMERA` (ponto vermelho) ↔ `SCREEN` (cursor vs centro da tela) |
| `C` | Calibrar o centro de mira: define a posição atual do ponto vermelho como origem (neutro). Sem ponto detectado, reseta para o centro do frame |
| `P` | Pausar/retomar a simulação de teclado/mouse (a webcam continua rodando) |
| `ESC` | Encerrar o programa |

## Dependências

```
opencv-python  # Processamento de vídeo
mediapipe      # Detecção de pose e mãos
numpy          # Operações numéricas
pyautogui      # Simulação de teclado/mouse (fallback)
pydirectinput  # Simulação de teclado/mouse (principal)
```

## Solução de Problemas

### MediaPipe não encontrado
```bash
pip install mediapipe
```

### Webcam não abre
- Verifique se a webcam está conectada e funcionando
- Tente: `python3.13 -c "import cv2; cap = cv2.VideoCapture(0); print(cap.isOpened())"`

### Movimento não é detectado
- Ajuste os thresholds em `CONFIG["THRESHOLDS"]`
- Certifique-se de estar bem iluminado
- Teste primeiro com `--disable-input` para visualizar a detecção

## Licença

Projeto para uso pessoal e educacional.
