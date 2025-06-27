# 🎯 DEXES - Sistema de Trading DeFi en Solana

<div align="center">

![Python](https://img.shields.io/badge/Python-3.13-blue.svg)
![Solana](https://img.shields.io/badge/Solana-Mainnet-green.svg)
![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)

**Sistema avanzado de trading automatizado para tokens en Solana, especializado en Pump.fun**

[Características](#-características) • [Instalación](#-instalación) • [Configuración](#-configuración) • [Uso](#-uso) • [Documentación](#-documentación)

</div>

---

## 📋 Descripción

DEXES es un sistema completo de trading DeFi que proporciona herramientas avanzadas para:

- **Trading automatizado** en Pump.fun con WebSocket en tiempo real
- **Análisis de portfolio** con valoración multi-API
- **Gestión segura de wallets** de Solana
- **Monitoreo de precios** desde múltiples fuentes
- **Arbitraje entre DEXs** usando Jupiter Protocol

## ✨ Características

### 🎯 Trading Automatizado
- Detección automática de nuevos tokens en Pump.fun
- Ejecución de trades con criterios personalizables
- Stop-loss y profit-target automáticos
- Monitoreo WebSocket en tiempo real

### 📊 Análisis de Portfolio
- Valoración completa de tokens SPL
- Integración con DexScreener, Jupiter, CoinGecko
- Análisis P&L detallado
- Alertas de precio configurables

### 🔐 Seguridad
- Gestión segura de claves privadas
- Validación de transacciones
- Límites de trading configurables
- Backup y recuperación de wallets

### 🌐 Integraciones
- **PumpPortal API**: Trading y WebSocket
- **DexScreener API**: Datos de mercado
- **Jupiter API**: Swaps y arbitraje
- **CoinGecko/Birdeye**: Precios de referencia

---

## 🚀 Instalación

### Prerrequisitos

- **Python 3.13+** (recomendado)
- **pip** (gestor de paquetes Python)
- **Git** (para clonar el repositorio)
- **Jupyter Notebook** (para interfaces interactivas)

### Verificar Instalación de Python

```bash
python --version
# Debe mostrar Python 3.13.x o superior
```

### 1. Clonar el Repositorio

```bash
git clone https://github.com/Mario-jesus/DEXES.git
cd DEXES
```

### 2. Instalar Dependencias

#### Opción A: Usando Pipenv (Recomendado)
```bash
# Instalar Pipenv si no lo tienes
pip install pipenv

# Instalar dependencias y crear entorno virtual automáticamente
pipenv install

# Activar entorno virtual
pipenv shell
```

#### Opción B: Usando Entorno Virtual Tradicional
```bash
# Crear entorno virtual
python -m venv dexes_env

# Activar entorno virtual
# En Windows:
dexes_env\Scripts\activate

# En macOS/Linux:
source dexes_env/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### 3. Instalar Jupyter (si no lo tienes)

```bash
# Si usas Pipenv
pipenv install jupyter

# Si usas pip tradicional
pip install jupyter notebook jupyterlab
```

---

## 📦 Dependencias Principales

### Core de Solana
```
solana==0.36.7
solders==0.25.1
anchorpy==0.22.0
```

### WebSocket y Networking
```
websockets==15.0.1
requests==2.32.4
aiohttp==3.11.10
```

### Análisis de Datos
```
pandas==2.2.3
numpy==2.2.1
```

### Notebooks y Utilidades
```
jupyter==1.1.1
python-dotenv==1.0.1
```

---

## ⚙️ Configuración Inicial

### 1. Crear Directorio de Wallets

```bash
mkdir wallets
chmod 700 wallets  # Solo en macOS/Linux
```

---

## 🎮 Uso Rápido

### 1. Iniciar Jupyter

```bash
jupyter notebook
```

### 2. Notebooks Disponibles

- **`DEXES_TRADING.ipynb`**: Consulta de precios, portfolio y trading
- **`PUMPFUN_TOOLS.ipynb`**: Monitoreo especializado de Pump.fun
- **`SOLANA_MANAGER_TOOLS.ipynb`**: Gestión de wallets

### 3. Primer Uso - Crear Wallet

Abre `SOLANA_MANAGER_TOOLS.ipynb` y ejecuta las celdas de creación de wallet:

```python
from solana_manager import SolanaWalletManager

# Crear nueva wallet
wallet_manager = SolanaWalletManager()
wallet_file = wallet_manager.create_wallet_file()
print(f"Wallet creada: {wallet_file}")
```

### 4. Consultar Portfolio

En `DEXES_TRADING.ipynb`:

```python
from dexscreener import DexScreenerPortfolioMonitor

# Cargar wallet y consultar balance
portfolio_monitor = DexScreenerPortfolioMonitor(wallet_manager)
portfolio_monitor.get_detailed_balance()
```

---

## 📁 Estructura del Proyecto

```
DEXES/
├── 📱 Notebooks Principales
│   ├── DEXES_TRADING.ipynb          # Trading y consultas
│   ├── PUMPFUN_TOOLS.ipynb          # Herramientas Pump.fun
│   └── SOLANA_MANAGER_TOOLS.ipynb   # Gestión de wallets
│
├── 🏗️ Módulos Core
│   ├── solana_manager/              # Gestión de wallets y cuentas
│   ├── pumpfun/                     # Trading en Pump.fun
│   ├── dexscreener/                 # Análisis de mercado
│   └── jupiter/                     # Arbitraje y swaps
│
├── 💳 Datos
│   └── wallets/                     # Archivos de wallet (crear)
│
├── 📋 Configuración
│   ├── requirements.txt             # Dependencias Python
│   ├── Pipfile                      # Configuración Pipenv
│   └── .env                         # Variables de entorno (crear)
│
└── 📚 Documentación
    └── README.md                    # Este archivo
```

---

## 🔧 Solución de Problemas

### Error: "ModuleNotFoundError"
```bash
# Si usas Pipenv
pipenv install

# Si usas entorno virtual tradicional
pip install -r requirements.txt
```

### Error: "Connection timeout"
- Verificar conexión a internet
- Probar con diferentes RPCs de Solana
- Revisar firewall/antivirus

### Error: "Permission denied" (wallets/)
```bash
# En macOS/Linux
chmod 700 wallets/
```

### Jupyter no encuentra módulos
```bash
# Si usas Pipenv
pipenv install ipykernel
pipenv run python -m ipykernel install --user --name=dexes

# Si usas entorno virtual tradicional
python -m ipykernel install --user --name=dexes_env
```

---

## 🛡️ Seguridad

### ⚠️ Advertencias Importantes

- **NUNCA** compartas tus archivos de wallet
- **NUNCA** subas wallets a repositorios públicos
- **SIEMPRE** haz backup de tus wallets
- **USA** montos pequeños para pruebas iniciales

### 🔐 Mejores Prácticas

1. **Wallets de Prueba**: Usa wallets separadas para testing
2. **Backups Seguros**: Guarda copias en múltiples ubicaciones
3. **Permisos Restrictivos**: Configura permisos 600 en archivos de wallet
4. **Monitoreo**: Revisa logs y transacciones regularmente

---

## 📚 Documentación Adicional

- **Notebooks**: Cada notebook incluye documentación inline
- **Código**: Todos los módulos están documentados
- **APIs**: Consulta documentación oficial de cada API integrada

---

## 🤝 Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

---

## ⚡ Inicio Rápido (Resumen)

```bash
# 1. Clonar y entrar al directorio
git clone https://github.com/Mario-jesus/DEXES.git && cd DEXES

# 2. Instalar Pipenv e instalar dependencias
pip install pipenv && pipenv install

# 3. Activar entorno virtual
pipenv shell

# 4. Crear directorio de wallets
mkdir wallets

# 5. Iniciar Jupyter
jupyter notebook

# 6. ¡Comenzar a usar DEXES! 🚀
```
