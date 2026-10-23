"""Registre d'outils.

Un registre plutôt qu'une liste de `if` : le schéma envoyé au modèle et la
fonction exécutée viennent du même objet. Quand les deux sont écrits à deux
endroits différents, ils divergent, et le modèle appelle un outil avec des
arguments que le code ne comprend plus.
"""

from agent.errors import UnknownToolError
from agent.models import ToolSpec


class ToolRegistry:
    """Les outils dont dispose l'agent, et rien d'autre.

    La surface d'outils est la vraie limite de ce qu'un agent peut faire. On
    ne se protège pas d'une injection de prompt en filtrant le texte : on s'en
    protège en ne donnant pas à l'agent le droit de faire la chose dangereuse.
    """

    def __init__(self, specs: list[ToolSpec]) -> None:
        names = [spec.name for spec in specs]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ValueError(f"Outils en double dans le registre : {duplicates}")
        self._specs = {spec.name: spec for spec in specs}

    def names(self) -> list[str]:
        """Noms des outils, dans l'ordre de déclaration."""
        return list(self._specs)

    def get(self, name: str) -> ToolSpec:
        """Rend la définition d'un outil, ou échoue en le nommant."""
        if name not in self._specs:
            raise UnknownToolError(
                f"Outil inconnu : {name!r}. Disponibles : {self.names()}."
            )
        return self._specs[name]

    def sensitiveNames(self) -> list[str]:
        """Noms des outils marqués sensibles."""
        return [spec.name for spec in self._specs.values() if spec.isSensitive]

    def schemas(self) -> list[dict[str, object]]:
        """Définitions d'outils au format attendu par l'API.

        La description dit au modèle **quand** utiliser l'outil, pas seulement
        ce qu'il fait. Pour un outil sensible, elle dit aussi que l'action est
        irréversible et soumise à validation : le modèle doit pouvoir en tenir
        compte avant de la demander, pas seulement après un refus.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.inputSchema,
                },
            }
            for spec in self._specs.values()
        ]
