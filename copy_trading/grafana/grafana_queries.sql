-- ============================================================================
-- CONSULTAS SQL PARA DASHBOARDS DE GRAFANA
-- Sistema de Monitoreo de Trading Metrics
-- ============================================================================

-- ============================================================================
-- 1. PNL TOTAL ACUMULADO POR SISTEMA (Time Series)
-- ============================================================================
-- Muestra la evolución del PnL total acumulado de cada sistema en el tiempo
SELECT
    timestamp AS time,
    system_name,
    metric_value AS "PnL Total (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'PNL_Total_Cumulative'
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode  -- Variable de Grafana: 'live' o 'dry_run'
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 2. PNL TOTAL DE TODOS LOS SISTEMAS (ALL_SYSTEMS) - Time Series
-- ============================================================================
-- Muestra el PnL agregado de todos los sistemas combinados
SELECT
    timestamp AS time,
    metric_value AS "PnL Total ALL_SYSTEMS (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'PNL_Total_Cumulative'
    AND system_name = 'ALL_SYSTEMS'
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 3. CAPITAL ACTUAL POR SISTEMA - Time Series
-- ============================================================================
-- Muestra la evolución del capital actual de cada sistema
SELECT
    timestamp AS time,
    system_name,
    metric_value AS "Capital Actual (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'Capital_Current'
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 4. CAPITAL TOTAL DE TODOS LOS SISTEMAS - Time Series
-- ============================================================================
-- Muestra el capital total agregado de todos los sistemas
SELECT
    timestamp AS time,
    metric_value AS "Capital Total ALL_SYSTEMS (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'Capital_Total'
    AND system_name = 'ALL_SYSTEMS'
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 5. DRAWDOWN TOTAL POR SISTEMA - Time Series
-- ============================================================================
-- Muestra el drawdown total de cada sistema en el tiempo
SELECT
    timestamp AS time,
    system_name,
    metric_value AS "Drawdown Total (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'Drawdown_Total'
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 6. DRAWDOWN INDIVIDUAL POR TRADER - Time Series
-- ============================================================================
-- Muestra el drawdown de cada trader individual
SELECT
    timestamp AS time,
    trader,
    metric_value AS "Drawdown Individual (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'Drawdown_Individual'
    AND system_name = $system_name  -- Variable de Grafana para filtrar por sistema
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 7. PNL INDIVIDUAL POR TRADER - Time Series
-- ============================================================================
-- Muestra el PnL acumulado de cada trader individual
SELECT
    timestamp AS time,
    trader,
    metric_value AS "PnL Individual (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'PNL_Individual_Cumulative'
    AND system_name = $system_name
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 8. ÚLTIMAS MÉTRICAS POR SISTEMA (Table Panel)
-- ============================================================================
-- Muestra las últimas métricas de cada sistema en formato tabla
SELECT
    system_name AS "Sistema",
    execution_mode AS "Modo",
    MAX(CASE WHEN metric_name = 'PNL_Total_Cumulative' THEN metric_value END) AS "PnL Total (SOL)",
    MAX(CASE WHEN metric_name = 'Capital_Current' THEN metric_value END) AS "Capital Actual (SOL)",
    MAX(CASE WHEN metric_name = 'Drawdown_Total' THEN metric_value END) AS "Drawdown Total (SOL)",
    MAX(timestamp) AS "Última Actualización"
FROM trading_metrics
WHERE 
    trader = 'ALL_TRADERS'
    AND system_name != 'ALL_SYSTEMS'
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
GROUP BY system_name, execution_mode
ORDER BY system_name;

-- ============================================================================
-- 9. COMPARATIVA DE SISTEMAS - PNL ACTUAL (Stat Panel)
-- ============================================================================
-- Muestra el PnL actual de cada sistema para comparación
SELECT
    system_name,
    metric_value AS "PnL Actual"
FROM trading_metrics
WHERE 
    metric_name = 'PNL_Total_Cumulative'
    AND trader = 'ALL_TRADERS'
    AND system_name != 'ALL_SYSTEMS'
    AND execution_mode = $execution_mode
    AND timestamp = (
        SELECT MAX(timestamp)
        FROM trading_metrics tm2
        WHERE tm2.system_name = trading_metrics.system_name
            AND tm2.metric_name = 'PNL_Total_Cumulative'
            AND tm2.trader = 'ALL_TRADERS'
            AND tm2.execution_mode = $execution_mode
    )
ORDER BY metric_value DESC;

-- ============================================================================
-- 10. TOP TRADERS POR PNL (Table Panel)
-- ============================================================================
-- Muestra los traders con mejor PnL en un sistema específico
SELECT
    trader AS "Trader",
    metric_value AS "PnL Acumulado (SOL)",
    timestamp AS "Última Actualización"
FROM trading_metrics
WHERE 
    metric_name = 'PNL_Individual_Cumulative'
    AND system_name = $system_name
    AND execution_mode = $execution_mode
    AND trader != 'ALL_TRADERS'
    AND timestamp = (
        SELECT MAX(timestamp)
        FROM trading_metrics tm2
        WHERE tm2.trader = trading_metrics.trader
            AND tm2.system_name = $system_name
            AND tm2.metric_name = 'PNL_Individual_Cumulative'
            AND tm2.execution_mode = $execution_mode
    )
ORDER BY metric_value DESC
LIMIT 10;

-- ============================================================================
-- 11. EVOLUCIÓN DE CAPITAL VS DRAWDOWN (Dual Axis)
-- ============================================================================
-- Muestra capital actual y drawdown en el mismo gráfico con dos ejes
SELECT
    timestamp AS time,
    MAX(CASE WHEN metric_name = 'Capital_Current' THEN metric_value END) AS "Capital Actual (SOL)",
    MAX(CASE WHEN metric_name = 'Drawdown_Total' THEN metric_value END) AS "Drawdown Total (SOL)"
FROM trading_metrics
WHERE 
    system_name = $system_name
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND metric_name IN ('Capital_Current', 'Drawdown_Total')
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
GROUP BY timestamp
ORDER BY timestamp ASC;

-- ============================================================================
-- 12. MÉTRICAS AGREGADAS ALL_SYSTEMS (Stat Panel)
-- ============================================================================
-- Muestra las métricas agregadas de todos los sistemas
SELECT
    metric_name,
    metric_value AS value
FROM trading_metrics
WHERE 
    system_name = 'ALL_SYSTEMS'
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND timestamp = (
        SELECT MAX(timestamp)
        FROM trading_metrics tm2
        WHERE tm2.system_name = 'ALL_SYSTEMS'
            AND tm2.trader = 'ALL_TRADERS'
            AND tm2.execution_mode = $execution_mode
    );

-- ============================================================================
-- 13. HISTÓRICO DE MÁXIMOS Y MÍNIMOS (Time Series)
-- ============================================================================
-- Muestra el capital máximo alcanzado y el capital actual para visualizar drawdown
SELECT
    timestamp AS time,
    system_name,
    metric_value AS "Capital Actual (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'Capital_Current'
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 14. DISTRIBUCIÓN DE PNL POR TRADER (Pie Chart)
-- ============================================================================
-- Muestra la distribución del PnL entre traders
SELECT
    trader AS "Trader",
    metric_value AS "PnL (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'PNL_Individual_Cumulative'
    AND system_name = $system_name
    AND execution_mode = $execution_mode
    AND trader != 'ALL_TRADERS'
    AND timestamp = (
        SELECT MAX(timestamp)
        FROM trading_metrics tm2
        WHERE tm2.system_name = $system_name
            AND tm2.metric_name = 'PNL_Individual_Cumulative'
            AND tm2.execution_mode = $execution_mode
            AND tm2.trader = trading_metrics.trader
    )
ORDER BY metric_value DESC;

-- ============================================================================
-- 15. COMPARATIVA LIVE VS DRY_RUN (Time Series)
-- ============================================================================
-- Compara el PnL entre modo live y dry_run
SELECT
    timestamp AS time,
    execution_mode,
    metric_value AS "PnL Total (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'PNL_Total_Cumulative'
    AND system_name = $system_name
    AND trader = 'ALL_TRADERS'
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 16. TASA DE CAMBIO DE PNL (Rate of Change)
-- ============================================================================
-- Calcula la tasa de cambio del PnL entre períodos
SELECT
    timestamp AS time,
    system_name,
    metric_value - LAG(metric_value) OVER (
        PARTITION BY system_name 
        ORDER BY timestamp
    ) AS "Cambio PnL (SOL)"
FROM trading_metrics
WHERE 
    metric_name = 'PNL_Total_Cumulative'
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC;

-- ============================================================================
-- 17. RESUMEN DE MÉTRICAS POR SISTEMA (Table Panel)
-- ============================================================================
-- Tabla resumen con todas las métricas principales por sistema
SELECT
    system_name AS "Sistema",
    execution_mode AS "Modo",
    MAX(CASE WHEN metric_name = 'PNL_Total_Cumulative' THEN metric_value END) AS "PnL Total",
    MAX(CASE WHEN metric_name = 'Capital_Current' THEN metric_value END) AS "Capital Actual",
    MAX(CASE WHEN metric_name = 'Drawdown_Total' THEN metric_value END) AS "Drawdown",
    MAX(timestamp) AS "Última Actualización"
FROM trading_metrics
WHERE 
    trader = 'ALL_TRADERS'
    AND system_name != 'ALL_SYSTEMS'
    AND execution_mode = $execution_mode
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
GROUP BY system_name, execution_mode
ORDER BY 
    MAX(CASE WHEN metric_name = 'PNL_Total_Cumulative' THEN metric_value END) DESC NULLS LAST;

-- ============================================================================
-- 18. ALERTAS: SISTEMAS CON DRAWDOWN ELEVADO
-- ============================================================================
-- Identifica sistemas con drawdown superior a un umbral
SELECT
    system_name AS "Sistema",
    metric_value AS "Drawdown (SOL)",
    timestamp AS "Última Actualización"
FROM trading_metrics
WHERE 
    metric_name = 'Drawdown_Total'
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND metric_value > $drawdown_threshold  -- Variable de Grafana para umbral
    AND timestamp = (
        SELECT MAX(timestamp)
        FROM trading_metrics tm2
        WHERE tm2.system_name = trading_metrics.system_name
            AND tm2.metric_name = 'Drawdown_Total'
            AND tm2.trader = 'ALL_TRADERS'
            AND tm2.execution_mode = $execution_mode
    )
ORDER BY metric_value DESC;

-- ============================================================================
-- 19. EVOLUCIÓN DE MÚLTIPLES MÉTRICAS (Multi-Metric Time Series)
-- ============================================================================
-- Muestra múltiples métricas en un solo gráfico
SELECT
    timestamp AS time,
    system_name,
    MAX(CASE WHEN metric_name = 'PNL_Total_Cumulative' THEN metric_value END) AS "PnL Total",
    MAX(CASE WHEN metric_name = 'Capital_Current' THEN metric_value END) AS "Capital Actual",
    MAX(CASE WHEN metric_name = 'Drawdown_Total' THEN metric_value END) AS "Drawdown"
FROM trading_metrics
WHERE 
    system_name = $system_name
    AND trader = 'ALL_TRADERS'
    AND execution_mode = $execution_mode
    AND metric_name IN ('PNL_Total_Cumulative', 'Capital_Current', 'Drawdown_Total')
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
GROUP BY timestamp, system_name
ORDER BY timestamp ASC;

-- ============================================================================
-- 20. MÉTRICAS DE ALL_SYSTEMS POR MODO DE EJECUCIÓN
-- ============================================================================
-- Compara métricas de ALL_SYSTEMS entre diferentes modos
SELECT
    timestamp AS time,
    execution_mode,
    metric_name,
    metric_value AS value
FROM trading_metrics
WHERE 
    system_name = 'ALL_SYSTEMS'
    AND trader = 'ALL_TRADERS'
    AND metric_name IN ('PNL_Total_Cumulative', 'Capital_Total')
    AND timestamp >= $__timeFrom()
    AND timestamp <= $__timeTo()
ORDER BY timestamp ASC, execution_mode, metric_name;

-- ============================================================================
-- NOTAS PARA GRAFANA:
-- ============================================================================
-- 1. Variables recomendadas para crear en Grafana:
--    - $execution_mode: Query variable con valores 'live', 'dry_run', 'all'
--    - $system_name: Query variable con valores de system_name únicos
--    - $drawdown_threshold: Variable numérica para umbral de alertas
--
-- 2. Para crear las variables:
--    SELECT DISTINCT execution_mode FROM trading_metrics;
--    SELECT DISTINCT system_name FROM trading_metrics WHERE system_name != 'ALL_SYSTEMS';
--
-- 3. Los campos timestamp deben usar alias 'time' para que Grafana los reconozca
--
-- 4. Usar $__timeFrom() y $__timeTo() para filtros de tiempo automáticos
--
-- 5. Para paneles Stat, usar la última consulta (más reciente timestamp)
--
-- 6. Para Time Series, ordenar por timestamp ASC
-- ============================================================================
