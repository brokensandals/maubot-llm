from maubot import Plugin
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from maubot import Plugin, MessageEvent
from maubot.handlers import event
from mautrix.types import EventType, MessageEvent
from typing import Type
from maubot_llm.backends import Backend, BasicOpenAIBackend
from maubot_llm import db
from mautrix.util.async_db import UpgradeTable


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("allowlist")
        helper.copy("default_backend")
        helper.copy("backends")


class LlmBot(Plugin):
    async def start(self) -> None:
        self.config.load_and_update()
    
    def is_allowed(self, sender: str) -> bool:
        if self.config["allowlist"] == False:
            return True
        return sender in self.config["allowlist"]

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config
    
    async def get_room(self, room_id: str) -> db.Room:
        room = await db.fetch_room(self.database, room_id)
        if room is None:
            room = db.Room()
            room.room_id = room_id
            await db.upsert_room(self.database, room)
        return room
    
    def get_backend(self, room: db.Room) -> Backend:
        key = room.backend
        if key is None:
            key = self.config["default_backend"]
        cfg = self.config["backends"][key]
        if cfg["type"] == "basic_openai":
            return BasicOpenAIBackend(cfg)
        raise ValueError(f"unknown backend type {cfg['type']}")
        

    @event.on(EventType.ROOM_MESSAGE)
    async def handle_msg(self, evt: MessageEvent) -> None:
        if not self.is_allowed(evt.sender):
            self.log.warn(f"stranger danger: sender={evt.sender}")
            return
        if evt.content.body.startswith("!"):
            return
        room = await self.get_room(evt.room_id)
        await db.append_context(self.database, room.room_id, "user", evt.content.body)
        await evt.mark_read()
        backend = self.get_backend(room)
        model = room.model or backend.default_model
        system = room.system_prompt or backend.default_system_prompt
        context = await db.fetch_context(self.database, room.room_id)
        completion = await backend.create_chat_completion(self.http, context=context, system=system, model=model)
        await db.append_context(self.database, room.room_id, completion.message["role"], completion.message["content"])
        await evt.respond(completion.message["content"])
    
    @classmethod
    def get_db_upgrade_table(cls) -> UpgradeTable | None:
        return db.upgrade_table
