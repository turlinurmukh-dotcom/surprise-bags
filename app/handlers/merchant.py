from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db.models import CATEGORY_LABELS, LISTING_CATEGORIES, Listing, Merchant
from app.db.session import get_session
from app.services.orders import PickupConfirmError, confirm_pickup
from app.timezone import format_almaty, parse_hhmm_today_almaty

router = Router()
logger = logging.getLogger(__name__)


def get_merchant_by_telegram_id(telegram_id: int) -> Merchant | None:
    session = get_session()
    try:
        return session.query(Merchant).filter_by(telegram_id=telegram_id).first()
    finally:
        session.close()


class PostListing(StatesGroup):
    category = State()
    original_price = State()
    discounted_price = State()
    quantity = State()
    pickup_start = State()
    pickup_end = State()
    confirm = State()


def _category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=CATEGORY_LABELS[c], callback_data=f"category:{c}")]
            for c in LISTING_CATEGORIES
        ]
    )


@router.message(Command("post_listing"))
async def start_post_listing(message: Message, state: FSMContext) -> None:
    merchant = get_merchant_by_telegram_id(message.from_user.id)
    if merchant is None:
        await message.answer(
            "You're not registered as a merchant yet. "
            "Ask the admin to add you (this is a manual step for now)."
        )
        return

    await state.update_data(merchant_id=merchant.id)
    await state.set_state(PostListing.category)
    await message.answer(
        "Let's post a surprise bag. Pick a category — consumers only see the "
        "category, never the specific contents, so the bag stays a surprise:",
        reply_markup=_category_keyboard(),
    )


@router.callback_query(PostListing.category, F.data.startswith("category:"))
async def got_category(callback: CallbackQuery, state: FSMContext) -> None:
    category = callback.data.split(":", 1)[1]
    if category not in LISTING_CATEGORIES:
        await callback.answer("Invalid category.", show_alert=True)
        return

    await state.update_data(category=category)
    await state.set_state(PostListing.original_price)
    await callback.message.edit_text(f"Category: {CATEGORY_LABELS[category]}")
    await callback.message.answer("Original price, in KZT (whole numbers only, e.g. 2500)?")
    await callback.answer()


@router.message(PostListing.original_price)
async def got_original_price(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("Please send a whole number, e.g. 2500.")
        return
    await state.update_data(original_price=int(message.text))
    await state.set_state(PostListing.discounted_price)
    await message.answer("Discounted price, in KZT?")


@router.message(PostListing.discounted_price)
async def got_discounted_price(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("Please send a whole number, e.g. 1000.")
        return

    data = await state.get_data()
    discounted_price = int(message.text)
    if discounted_price >= data["original_price"]:
        await message.answer(
            "Discounted price should be lower than the original price. Try again."
        )
        return

    await state.update_data(discounted_price=discounted_price)
    await state.set_state(PostListing.quantity)
    await message.answer("How many bags are available?")


@router.message(PostListing.quantity)
async def got_quantity(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Please send a positive whole number.")
        return
    await state.update_data(quantity=int(message.text))
    await state.set_state(PostListing.pickup_start)
    await message.answer(
        "Pickup window start time today, Almaty time, 24h format, one time only (e.g. 18:00)?"
    )


@router.message(PostListing.pickup_start)
async def got_pickup_start(message: Message, state: FSMContext) -> None:
    start = parse_hhmm_today_almaty(message.text)
    if start is None:
        await message.answer(
            "Please send a single time like 18:00 (Almaty time) — "
            "just the start, not a range."
        )
        return
    await state.update_data(pickup_start=start.isoformat())
    await state.set_state(PostListing.pickup_end)
    await message.answer(
        "Pickup window end time today, Almaty time, 24h format, one time only (e.g. 20:00)?"
    )


@router.message(PostListing.pickup_end)
async def got_pickup_end(message: Message, state: FSMContext) -> None:
    logger.info("got_pickup_end: raw input=%r from user=%s", message.text, message.from_user.id)

    end = parse_hhmm_today_almaty(message.text)
    if end is None:
        logger.info("got_pickup_end: failed to parse %r as HH:MM", message.text)
        await message.answer(
            "Please send a single time like 20:00 (Almaty time) — "
            "just the end, not a range."
        )
        return

    data = await state.get_data()
    if "pickup_start" not in data:
        logger.error(
            "got_pickup_end: no pickup_start in FSM data (state may have been lost); data=%s",
            data,
        )
        await message.answer(
            "Something went wrong tracking your progress — let's restart. Send /post_listing again."
        )
        await state.clear()
        return

    start = datetime.fromisoformat(data["pickup_start"])
    if end <= start:
        logger.info("got_pickup_end: end %s <= start %s, rejecting", end, start)
        await message.answer("End time must be after the start time. Try again.")
        return

    await state.update_data(pickup_end=end.isoformat())
    data = await state.get_data()
    logger.info("got_pickup_end: valid window %s-%s, moving to confirm", start, end)

    summary = (
        "Here's your listing:\n\n"
        f"{CATEGORY_LABELS[data['category']]}\n"
        f"Price: {data['original_price']} KZT → {data['discounted_price']} KZT\n"
        f"Quantity: {data['quantity']}\n"
        f"Pickup: {format_almaty(start)}–{format_almaty(end)} (Almaty time)\n\n"
        "Post it?"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Confirm", callback_data="listing_confirm"),
                InlineKeyboardButton(text="Cancel", callback_data="listing_cancel"),
            ]
        ]
    )
    await state.set_state(PostListing.confirm)
    await message.answer(summary, reply_markup=keyboard)


@router.callback_query(PostListing.confirm, F.data == "listing_confirm")
async def confirm_listing(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    logger.info("confirm_listing: submitting with data=%s", data)

    session = get_session()
    try:
        listing = Listing(
            merchant_id=data["merchant_id"],
            category=data["category"],
            original_price=data["original_price"],
            discounted_price=data["discounted_price"],
            quantity_total=data["quantity"],
            quantity_remaining=data["quantity"],
            pickup_window_start=datetime.fromisoformat(data["pickup_start"]),
            pickup_window_end=datetime.fromisoformat(data["pickup_end"]),
            status="active",
        )
        session.add(listing)
        session.commit()
        listing_id = listing.id
    finally:
        session.close()

    await state.clear()
    await callback.message.edit_text(f"Posted! Listing #{listing_id} is now live.")
    await callback.answer()


@router.callback_query(PostListing.confirm, F.data == "listing_cancel")
async def cancel_listing(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("cancel_listing: user=%s cancelled at confirm step", callback.from_user.id)
    await state.clear()
    await callback.message.edit_text("Cancelled. No listing was posted.")
    await callback.answer()


@router.callback_query(F.data.in_(("listing_confirm", "listing_cancel")))
async def stale_confirm_callback(callback: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()
    logger.warning(
        "stale confirm/cancel callback: data=%r arrived while state=%r (user=%s) — "
        "listing FSM had already moved on, likely a duplicate/late Telegram update",
        callback.data,
        current_state,
        callback.from_user.id,
    )
    await callback.answer(
        "This listing form has expired or was already submitted. Send /post_listing to start again.",
        show_alert=True,
    )


@router.message(Command("pickup"))
async def pickup(message: Message, command: CommandObject) -> None:
    merchant = get_merchant_by_telegram_id(message.from_user.id)
    if merchant is None:
        await message.answer("You're not registered as a merchant yet.")
        return

    code = (command.args or "").strip()
    if not code:
        await message.answer("Usage: /pickup <code> — e.g. /pickup A1B2C3")
        return

    session = get_session()
    try:
        try:
            order = confirm_pickup(session, merchant, code)
        except PickupConfirmError as exc:
            await message.answer(str(exc))
            return
        listing_category = CATEGORY_LABELS[order.listing.category]
    finally:
        session.close()

    await message.answer(f"Confirmed — {listing_category} picked up. Nice work!")


@router.message(Command("my_listings"))
async def my_listings(message: Message) -> None:
    merchant = get_merchant_by_telegram_id(message.from_user.id)
    if merchant is None:
        await message.answer("You're not registered as a merchant yet.")
        return

    session = get_session()
    try:
        listings = (
            session.query(Listing)
            .filter_by(merchant_id=merchant.id)
            .order_by(Listing.created_at.desc())
            .limit(10)
            .all()
        )
    finally:
        session.close()

    if not listings:
        await message.answer("You haven't posted any listings yet. Try /post_listing.")
        return

    lines = ["Your recent listings:\n"]
    for listing in listings:
        lines.append(
            f"#{listing.id} [{listing.status}] {CATEGORY_LABELS[listing.category]} — "
            f"{listing.quantity_remaining}/{listing.quantity_total} left, "
            f"{listing.discounted_price} KZT"
        )
    await message.answer("\n".join(lines))
