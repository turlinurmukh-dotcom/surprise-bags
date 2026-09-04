import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

router = Router()
logger = logging.getLogger(__name__)


@router.message()
async def unhandled_message(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    logger.warning(
        "unhandled message: text=%r from user=%s in state=%r",
        message.text,
        message.from_user.id,
        current_state,
    )
    await message.answer(
        "Sorry, I didn't understand that. Try /app to browse surprise bags, "
        "/my_orders to check your reservations, /post_listing to post a bag, "
        "or /pickup <code> (with a space) to confirm a pickup."
    )


@router.callback_query()
async def unhandled_callback(callback: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()
    logger.warning(
        "unhandled callback: data=%r from user=%s in state=%r",
        callback.data,
        callback.from_user.id,
        current_state,
    )
    await callback.answer("This action is no longer available.", show_alert=True)
