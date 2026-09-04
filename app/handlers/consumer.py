from __future__ import annotations

import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.db.session import get_session
from app.services.listings import (
    ReservationError,
    active_listings,
    get_or_create_user,
    listing_to_card,
    reserve_listing,
)
from app.services.orders import user_orders
from app.timezone import format_almaty

router = Router()


def _reserve_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Reserve", callback_data=f"reserve:{listing_id}")]
        ]
    )


@router.message(Command("start"))
async def start(message: Message) -> None:
    session = get_session()
    try:
        get_or_create_user(session, message.from_user.id, message.from_user.username)
    finally:
        session.close()
    await message.answer(
        "Welcome! Use /browse to see today's surprise bags, "
        "or /my_orders to check your reservations."
    )


@router.message(Command("app"))
async def open_app(message: Message) -> None:
    webapp_url = os.getenv("WEBAPP_URL")
    if not webapp_url:
        await message.answer("The app isn't configured yet (WEBAPP_URL is unset).")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Open Surprise Bags", web_app=WebAppInfo(url=webapp_url))]
        ]
    )
    await message.answer("Browse today's surprise bags:", reply_markup=keyboard)


@router.message(Command("browse"))
async def browse(message: Message) -> None:
    session = get_session()
    try:
        cards = [listing_to_card(listing) for listing in active_listings(session)]
    finally:
        session.close()

    if not cards:
        await message.answer("No surprise bags available right now. Check back later!")
        return

    for card in cards:
        caption = (
            f"{card['merchant_name']} — {card['location_text']}\n"
            f"{card['category_label']}\n"
            f"~~{card['original_price']} KZT~~ → {card['discounted_price']} KZT\n"
            f"{card['quantity_remaining']} left\n"
            f"Pickup: {format_almaty(card['pickup_window_start'])}"
            f"–{format_almaty(card['pickup_window_end'])} (Almaty time)"
        )
        keyboard = _reserve_keyboard(card["id"])
        if card["merchant_photo_file_id"]:
            await message.answer_photo(
                card["merchant_photo_file_id"], caption=caption, reply_markup=keyboard
            )
        else:
            await message.answer(caption, reply_markup=keyboard)


@router.callback_query(F.data.startswith("reserve:"))
async def reserve(callback: CallbackQuery) -> None:
    listing_id = int(callback.data.split(":", 1)[1])

    session = get_session()
    try:
        user = get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        try:
            order = reserve_listing(session, listing_id, user)
        except ReservationError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        pickup_code = order.pickup_code
    finally:
        session.close()

    await callback.answer("Nice catch!")
    await callback.message.answer(
        f"Nice catch! Your pickup code is {pickup_code}.\n"
        "Show this code at pickup. Payment: pending (pay on pickup for now)."
    )


_STATUS_LABELS = {
    "reserved": "upcoming",
    "picked_up": "picked up",
    "no_show": "expired (no-show)",
    "cancelled": "cancelled",
}


@router.message(Command("my_orders"))
async def my_orders(message: Message) -> None:
    session = get_session()
    try:
        user = get_or_create_user(session, message.from_user.id, message.from_user.username)
        orders = user_orders(session, user)
    finally:
        session.close()

    if not orders:
        await message.answer("You have no orders yet. Try /browse.")
        return

    lines = ["Your recent orders:\n"]
    for order in orders:
        status_label = _STATUS_LABELS.get(order["status"], order["status"])
        lines.append(
            f"#{order['id']} [{status_label}] {order['category_label']} "
            f"from {order['merchant_name']} — code {order['pickup_code']}"
        )
    await message.answer("\n".join(lines))
