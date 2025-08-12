# 🎯 DEXES - Sistema de Trading DeFi en Solana

<div align="center">

![Python](https://img.shields.io/badge/Python-3.13-blue.svg)
![Solana](https://img.shields.io/badge/Solana-Mainnet-green.svg)
![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)
![Architecture](https://img.shields.io/badge/Architecture-Async-brightgreen.svg)

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
- **Análisis on-chain** con BitQuery
- **Liquidación automática** de posiciones
- **Tracking de traders** en tiempo real

## ✨ Características

### 🎯 Trading Automatizado
- Detección automática de nuevos tokens en Pump.fun
- Ejecución de trades con criterios personalizables
- Stop-loss y profit-target automáticos
- Monitoreo WebSocket en tiempo real
- **Transacciones Lightning** de Pump.fun
- **Liquidación automática** de posiciones completas

### 📊 Análisis Avanzado
- Valoración completa de tokens SPL
- Integración con DexScreener, Jupiter, CoinGecko
- Análisis P&L detallado con historial
- Alertas de precio configurables
- **Análisis de transacciones on-chain**
- **Tracking de traders top**
- **Análisis de pumps** y tendencias

### 🔐 Seguridad
- Gestión segura de claves privadas
- Validación de transacciones
- Límites de trading configurables
- Backup y recuperación de wallets
- **Permisos restrictivos** en archivos de wallet
- **Modo de prueba** para testing

### 🌐 Integraciones
- **PumpPortal API**: Trading y WebSocket
- **DexScreener API**: Datos de mercado
- **Jupiter API**: Swaps y arbitraje
- **BitQuery API**: Análisis on-chain
- **CoinGecko/Birdeye**: Precios de referencia

### 🏗️ Arquitectura
- **Completamente asíncrono** (AsyncIO)
- **Patrón Singleton** para clientes API
- **Context managers** para gestión de recursos
- **Sistema de logging** centralizado
- **Modular** y extensible

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
solders==0.26.0
anchorpy==0.22.0
```

### WebSocket y Networking
```
websockets==15.0.1
requests==2.32.4
aiohttp==3.12.13
```

### Análisis de Datos
```
pandas==2.3.1
numpy==2.3.1
```

### Notebooks y Utilidades
```
jupyter==1.1.1
python-dotenv==1.1.1
python-telegram-bot==22.2
```

---

## ⚙️ Configuración Inicial

### 1. Crear Directorio de Wallets

```bash
mkdir wallets
chmod 700 wallets  # Solo en macOS/Linux
```

### 2. Variables de Entorno (Opcional)

Crear archivo `.env` para configuraciones avanzadas:

```bash
# API Keys (opcionales)
BITQUERY_API_KEY=your_bitquery_api_key
PUMPFUN_API_KEY=your_pumpfun_api_key

# Configuración de red
SOLANA_NETWORK=mainnet-beta
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com

# Configuración de trading
DEFAULT_SLIPPAGE=15.0
DEFAULT_PRIORITY_FEE=0.0001
```

---

## 🎮 Uso Rápido

### 1. Iniciar Jupyter

```bash
jupyter notebook
```

### 2. Notebooks Disponibles

- **`DEXES_TRADING.ipynb`**: Trading, consultas de precios y portfolio
- **`PUMPFUN_TOOLS.ipynb`**: Herramientas especializadas de Pump.fun
- **`SOLANA_MANAGER_TOOLS.ipynb`**: Gestión completa de wallets
- **`BITQUERY.ipynb`**: Análisis on-chain y tracking de traders

### 3. Primer Uso - Crear Wallet

Abre `SOLANA_MANAGER_TOOLS.ipynb` y ejecuta las celdas de creación de wallet:

```python
from solana_manager import SolanaWalletManager

# Crear nueva wallet
async with SolanaWalletManager(network="mainnet-beta") as wallet_manager:
    wallet_file = await wallet_manager.create_wallet_file()
    print(f"Wallet creada: {wallet_file}")
```

### 4. Consultar Portfolio

En `DEXES_TRADING.ipynb`:

```python
from dexscreener import DexScreenerPortfolioMonitor, DexScreenerPriceTracker

# Configurar monitor de portfolio
price_tracker = DexScreenerPriceTracker()
portfolio_monitor = DexScreenerPortfolioMonitor(wallet_address, price_tracker)

# Obtener balance detallado
async with portfolio_monitor:
    await portfolio_monitor.get_detailed_balance()
```

### 5. Análisis de Transacciones

En `PUMPFUN_TOOLS.ipynb`:

```python
from pumpfun import PumpFunTradeAnalyzer

# Analizar transacción específica
async with PumpFunTradeAnalyzer() as analyzer:
    trade_info = await analyzer.analyze_transaction_by_signature(signature)
    print(trade_info)
```

### 6. Tracking de Traders

En `BITQUERY.ipynb`:

```python
from bitquery import BitQueryHTTPClient, display_pumpfun_traders

# Obtener top traders
async with BitQueryHTTPClient() as client:
    result = await client.get_pumpfun_top_traders_filtered(limit=10)
    display_pumpfun_traders(result)
```

---

## 📁 Estructura del Proyecto

```
DEXES/
├── 📱 Notebooks Principales
│   ├── DEXES_TRADING.ipynb          # Trading y consultas
│   ├── PUMPFUN_TOOLS.ipynb          # Herramientas Pump.fun
│   ├── SOLANA_MANAGER_TOOLS.ipynb   # Gestión de wallets
│   └── BITQUERY.ipynb               # Análisis on-chain
│
├── 🏗️ Módulos Core
│   ├── solana_manager/              # Gestión de wallets y cuentas
│   │   ├── wallet_manager.py        # Creación y gestión de wallets
│   │   ├── account_info.py          # Consulta de balances
│   │   ├── transfer_manager.py      # Transferencias
│   │   └── utils.py                 # Utilidades
│   │
│   ├── pumpfun/                     # Trading en Pump.fun
│   │   ├── api_client.py            # Cliente API centralizado
│   │   ├── transactions.py          # Transacciones Lightning
│   │   ├── pumpfun_trade_analyzer.py # Análisis de trades
│   │   ├── wallet_manager.py        # Gestión específica
│   │   ├── subscriptions.py         # WebSocket subscriptions
│   │   └── utils/                   # Utilidades adicionales
│   │       └── liquidate_positions.py # Liquidación automática
│   │
│   ├── dexscreener/                 # Análisis de mercado
│   │   ├── price_tracker.py         # Tracking de precios
│   │   ├── portfolio_monitor.py     # Monitoreo de portfolio
│   │   ├── token_scanner.py         # Scanner de tokens
│   │   └── pump_analyzer.py         # Análisis de pumps
│   │
│   ├── jupiter/                     # Arbitraje y swaps
│   │   └── jupiter_dex.py           # Integración Jupiter
│   │
│   ├── bitquery/                    # Análisis on-chain
│   │   ├── http_client.py           # Cliente HTTP
│   │   ├── websocket_client.py      # Cliente WebSocket
│   │   ├── queries.py               # Queries GraphQL
│   │   └── analysis.py              # Funciones de análisis
│   │
│   └── logging_system/              # Sistema de logging
│       ├── custom_logger.py         # Logger personalizado
│       └── logger_config.py         # Configuración
│
├── 💳 Datos
│   └── wallets/                     # Archivos de wallet (crear)
│
├── 📋 Configuración
│   ├── requirements.txt             # Dependencias Python
│   ├── Pipfile                      # Configuración Pipenv
│   ├── docker-compose.yaml          # Configuración Docker
│   ├── Dockerfile                   # Imagen Docker
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

### Error de versiones de dependencias
```bash
# Actualizar dependencias
pipenv update

# O reinstalar completamente
pipenv --rm
pipenv install
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
3. **Permisos Restrictivos**: Configura permisos 700 en directorio wallets
4. **Monitoreo**: Revisa logs y transacciones regularmente
5. **API Keys**: Usa variables de entorno para API keys
6. **Modo de Prueba**: Siempre prueba en devnet primero

---

## 📚 Documentación Adicional

- **Notebooks**: Cada notebook incluye documentación inline
- **Código**: Todos los módulos están documentados
- **APIs**: Consulta documentación oficial de cada API integrada
- **Ejemplos**: Revisa los notebooks para ejemplos prácticos

---

## 📊 Casos de Uso Avanzados

### Trading Automatizado
```python
# Configurar bot de trading
from pumpfun import PumpFunTransactions, PumpFunApiClient

async with PumpFunTransactions() as tx_manager:
    # Ejecutar trade automático
    signature = await tx_manager.create_and_send_local_trade(
        keypair=keypair,
        action="buy",
        mint=token_mint,
        amount=0.1,  # SOL
        denominated_in_sol=True,
        slippage=15.0
    )
```

### Liquidación Automática
```python
# Liquidar todas las posiciones
from pumpfun.utils.liquidate_positions import liquidate_all_tokens

await liquidate_all_tokens(
    wallet_address=wallet_address,
    keypair=keypair,
    test_mode=False  # Cambiar a True para pruebas
)
```

### Análisis de Traders
```python
# Tracking en tiempo real
from bitquery import BitQueryWebSocketClient

async with BitQueryWebSocketClient() as client:
    await client.track_trader_realtime(
        trader_address,
        callback_function,
        duration_minutes=5
    )
```

---

## 📈 Estado del Proyecto

- ✅ **Activo** y en desarrollo continuo
- ✅ **Documentación completa** y actualizada
- ✅ **Docker** configurado y funcional
- ✅ **Dependencias** actualizadas a las últimas versiones
- ✅ **Sistema de logging** estratégico implementado
- ✅ **Código asíncrono** optimizado para alto rendimiento
- ✅ **Arquitectura modular** para fácil mantenimiento
- ✅ **Integración completa** con múltiples APIs

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
