"""
Lista fija de departamentos de Bolivia usada por la Fundación.

Única fuente de verdad en el backend: valida `User.depto_asignado`
(RESPONSABLE_DEPARTAMENTAL) y el query param `depto` del router
`departmental`. El campo `Patient.depto` sigue siendo texto libre sin
validar (no se cambia ese comportamiento aquí), por eso el matching contra
esta lista se hace de forma tolerante (ver `app.core.text_normalize`).
"""

DEPARTAMENTOS = [
    "La Paz", "Cochabamba", "Santa Cruz", "Oruro",
    "Potosí", "Chuquisaca", "Tarija", "Beni", "Pando",
]

# Departamentos donde la Fundación asigna un RESPONSABLE_DEPARTAMENTAL.
# Pando queda excluido: no hay responsable en ese departamento. La lista
# completa (con Pando) se sigue usando para el filtro opcional del
# Coordinador Nacional y para no rechazar datos históricos de Patient.depto.
DEPARTAMENTOS_RESPONSABLE = [d for d in DEPARTAMENTOS if d != "Pando"]
