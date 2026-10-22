"""Errores del juego con mensajes pensados para mostrarse al jugador."""


class GameError(Exception):
    """Error 'esperado' del juego. Su mensaje se puede enseñar tal cual en Discord."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CharacterAlreadyExists(GameError):
    def __init__(self):
        super().__init__("Ya tienes un personaje. Solo se permite uno por jugador.")


class NoCharacter(GameError):
    def __init__(self):
        super().__init__("Todavía no tienes personaje. Crea uno con `/crear`.")


class InvalidName(GameError):
    pass


class NameTaken(GameError):
    def __init__(self):
        super().__init__("Ese nombre ya está en uso. Elige otro.")


class UnknownClass(GameError):
    def __init__(self):
        super().__init__("Esa clase no existe. Elige una de la lista.")


class InvalidAttribute(GameError):
    def __init__(self):
        super().__init__("Ese atributo no existe.")


class InvalidAmount(GameError):
    def __init__(self):
        super().__init__("La cantidad no es válida.")


class NotEnoughPoints(GameError):
    def __init__(self, available: int):
        super().__init__(f"No tienes suficientes puntos libres (tienes {available}).")


class UnknownExpedition(GameError):
    def __init__(self):
        super().__init__("Esa expedición no existe. Mira la lista con `/expedicion`.")


class LevelTooLow(GameError):
    def __init__(self, name: str, min_level: int):
        super().__init__(f"**{name}** requiere nivel {min_level} como mínimo.")


class ExpeditionInProgress(GameError):
    def __init__(self):
        super().__init__("Tu personaje ya está en una expedición. Usa `/reclamar` para recoger sus resultados.")


class NoActiveExpedition(GameError):
    def __init__(self):
        super().__init__("No tienes ninguna expedición en curso. Empieza una con `/expedicion`.")


class NothingToClaimYet(GameError):
    def __init__(self, seconds: int | None):
        self.seconds = seconds
        super().__init__("Tu personaje todavía no se ha topado con nada. Vuelve un poco más tarde.")


class ItemNotFound(GameError):
    def __init__(self):
        super().__init__("No encuentro ese objeto en tu inventario.")


class ItemAlreadyEquipped(GameError):
    def __init__(self):
        super().__init__("Ese objeto ya está equipado.")


class ItemEquippedCannotSell(GameError):
    def __init__(self):
        super().__init__("No puedes vender un objeto equipado. Desequípalo primero.")


class ItemLevelTooLow(GameError):
    def __init__(self, name: str, min_level: int):
        super().__init__(f"**{name}** requiere nivel {min_level}.")


class InvalidSlot(GameError):
    def __init__(self):
        super().__init__("Esa ranura no existe.")


class NothingEquipped(GameError):
    def __init__(self):
        super().__init__("No tienes nada equipado en esa ranura.")


class InvalidSkill(GameError):
    def __init__(self):
        super().__init__("Esa habilidad no existe o no es de tu clase.")


class SkillLocked(GameError):
    def __init__(self, name: str, level: int):
        super().__init__(f"**{name}** se desbloquea en el nivel {level}.")


class DuplicateSkill(GameError):
    def __init__(self):
        super().__init__("Debes equipar dos habilidades distintas.")


class InvalidMode(GameError):
    def __init__(self):
        super().__init__("Ese modo de definitiva no existe.")


class InvalidResource(GameError):
    def __init__(self):
        super().__init__("Ese recurso no existe. Puedes donar oro o materiales.")


class NotEnoughResource(GameError):
    def __init__(self, available: int):
        super().__init__(f"No tienes suficiente (tienes {available}).")


class UnknownUpgrade(GameError):
    def __init__(self):
        super().__init__("Esa mejora no existe.")


class UpgradeMaxLevel(GameError):
    def __init__(self, name: str):
        super().__init__(f"**{name}** ya está al nivel máximo.")


class StorageShort(GameError):
    def __init__(self, missing: dict):
        self.missing = missing
        super().__init__("Al almacén le faltan recursos para esa mejora.")


class UnknownDungeon(GameError):
    def __init__(self):
        super().__init__("Esa mazmorra no existe.")


class DungeonLevelTooLow(GameError):
    def __init__(self, name: str, level: int):
        super().__init__(f"**{name}** requiere nivel {level} como mínimo.")


class AlreadyInDungeon(GameError):
    def __init__(self):
        super().__init__("Ya estás en una partida de mazmorra. Usa `/mazmorra estado` o `/mazmorra abandonar`.")


class NotInDungeon(GameError):
    def __init__(self):
        super().__init__("No estás en ninguna partida de mazmorra.")


class RunNotFound(GameError):
    def __init__(self):
        super().__init__("Esa partida no existe o ya no admite jugadores.")


class RunFull(GameError):
    def __init__(self):
        super().__init__("La partida está completa.")


class NotLeader(GameError):
    def __init__(self):
        super().__init__("Solo el líder de la partida puede hacer eso.")


class NotEnoughPlayers(GameError):
    def __init__(self, minimum: int):
        super().__init__(f"Hacen falta al menos {minimum} jugadores para empezar.")


class RunNotActive(GameError):
    def __init__(self):
        super().__init__("La partida todavía no ha empezado o ya ha terminado.")


class InvalidAction(GameError):
    pass


class OfferNotFound(GameError):
    def __init__(self):
        super().__init__("Esa oferta no existe o ya caducó: la tienda se renueva cada día. Mira `/tienda ver`.")


class OfferAlreadyBought(GameError):
    def __init__(self):
        super().__init__("Ya has comprado esa oferta hoy. Mañana habrá otras.")


class NotEnoughGold(GameError):
    def __init__(self, price: int, have: int):
        self.price, self.have = price, have
        super().__init__(f"Te faltan {price - have} de oro (cuesta {price}, tienes {have}).")


class InventoryFull(GameError):
    def __init__(self):
        super().__init__("Tu inventario está lleno. Vende algo con `/vender` o amplía la mochila en la tienda.")


class BagMaxed(GameError):
    def __init__(self):
        super().__init__("Tu mochila ya está al máximo.")


class NothingToRespec(GameError):
    def __init__(self):
        super().__init__("No tienes puntos gastados que recuperar.")
