# Huawei FusionSolar (Home Assistant Custom Integration)

Integracion personalizada para Home Assistant que obtiene datos de FusionSolar (inversores Huawei) usando login web y endpoints internos.

## Caracteristicas

- Configuracion por UI (`Config Flow`)
- Login con usuario/clave y reautenticacion
- Soporte multi-planta
- Sensores de potencia y energia:
  - Potencia actual (W)
  - Energia diaria (kWh)
  - Energia mensual (kWh)
  - Energia anual (kWh)
  - Energia total (kWh)
- Intervalo de polling configurable

## Instalacion con HACS (Custom Repository)

1. Sube este repositorio a GitHub.
2. En Home Assistant abre HACS.
3. Ve a `Integrations` > menu de tres puntos > `Custom repositories`.
4. Agrega la URL del repositorio y selecciona categoria `Integration`.
5. Busca `Huawei FusionSolar` en HACS e instalalo.
6. Reinicia Home Assistant.
7. Ve a `Settings` > `Devices & Services` > `Add Integration` y agrega `Huawei FusionSolar`.

## Instalacion manual

Copiar `custom_components/huawei_fusionsolar` dentro de `/config/custom_components/` y reiniciar Home Assistant.

## Estado

Version inicial: `0.1.0`.

## Nota de seguridad

Si compartiste credenciales durante pruebas, cambia la contrasena de FusionSolar al terminar.
