import asyncio
import time
import os
import re
from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher, FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram import executor
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Retrieve the bot token from the environment variables
API_TOKEN = os.getenv("API_TOKEN")

# Check if the API_TOKEN is present
if API_TOKEN is None:
    raise Exception(
        "API_TOKEN not found in the .env file. Make sure to create a .env file with API_TOKEN."
    )

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

active_timers = {}


class TimerStates:
    SETTING_DURATION = "setting_duration"
    SETTING_TEXT = "setting_text"
    SETTING_TIMER = "setting_timer"



async def format_duration(total_seconds):
    days, remainder = divmod(total_seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(days):02d}d {int(hours):02d}h {int(minutes):02d}m {int(seconds):02d}s"


async def send_timer_update(chat_id, message_id, duration, text):
    while duration > 0:
        formatted_duration = await format_duration(duration)
        await bot.edit_message_text(
            f"Time remaining: {formatted_duration} for {text}",
            chat_id=chat_id,
            message_id=message_id,
        )
        await asyncio.sleep(1)  # Update every 1 second
        duration -= 1


async def pin_timer_message(chat_id, message_id, duration):
    formatted_duration = await format_duration(duration)
    await bot.pin_chat_message(chat_id, message_id, disable_notification=True)
    await bot.edit_message_text(
        f"Pinned: Time remaining: {formatted_duration}",
        chat_id=chat_id,
        message_id=message_id,
    )


@dp.message_handler(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply("Welcome! This bot will help you set a countdown timer.")


@dp.message_handler(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "This bot allows you to set countdown timers. Here are the available commands:\n"
        "/setcountdowntimer - Set a new countdown timer\n"
        "/canceltimer - Cancel the current countdown timer\n"
        "/help - Show this help message"
    )
    await message.reply(help_text)


@dp.message_handler(Command("setcountdowntimer"))
async def cmd_set_timer(message: types.Message, state: FSMContext):
    chat_id = message.chat.id

    # Check if there is an active timer in the channel
    if chat_id in active_timers:
        await message.reply(
            "A timer is already running in this channel. You cannot set a new timer."
        )
    else:
        await message.reply("Please enter the timer duration in the format 'dd hh mm'.")
        await state.set_state(TimerStates.SETTING_DURATION)


@dp.message_handler(state=TimerStates.SETTING_DURATION)
async def set_timer_duration(message: types.Message, state: FSMContext):
    duration_input = message.text
    duration_pattern = re.compile(r'^(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})$')

    match = duration_pattern.match(duration_input)
    if match:
        days, hours, minutes = map(int, match.groups())
        total_seconds = days * 24 * 60 * 60 + hours * 60 * 60 + minutes * 60
        if total_seconds > 0:
            await state.update_data(duration=total_seconds)
            await message.reply("Please enter a text message to go with the timer.")
            await state.set_state(TimerStates.SETTING_TEXT)
        else:
            await message.reply("Please enter a positive duration.")
    else:
        await message.reply("Invalid input. Please enter the duration in the format 'dd hh mm'.")

@dp.message_handler(state=TimerStates.SETTING_TEXT)
async def set_timer_text(message: types.Message, state: FSMContext):
    text = message.text
    if text:
        await state.update_data(text=text)
        await message.reply(
            f"Timer text set to: {text}. Do you want to start the timer? (yes/no)"
        )
        await state.set_state(TimerStates.SETTING_TIMER)
    else:
        await message.reply("Text message cannot be empty.")
        await state.finish()


async def run_timer(duration, text, chat_id):
    end_time = time.time() + duration
    remaining_time = max(0, end_time - time.time())

    sent_message = await bot.send_message(
        chat_id,
        f"Time remaining: {await format_duration(duration)} for {text}",
    )

    # Store the message ID in the active_timers dictionary
    active_timers[chat_id] = {
        "task": asyncio.current_task(),
        "message_id": sent_message.message_id,
    }

    await asyncio.sleep(remaining_time)

    completion_message = f"Timer {text} complete!"
    sent_message = await bot.send_message(chat_id, completion_message)
    await bot.pin_chat_message(chat_id, sent_message.message_id)

    # Reset the active timer variable for the specific channel
    del active_timers[chat_id]


async def cancel_timer(chat_id):
    if chat_id in active_timers:
        # Retrieve the message ID from the active_timers dictionary
        message_id = active_timers[chat_id].get("message_id")

        if message_id:
            # Delete the pinned message
            await bot.unpin_chat_message(chat_id)
            await bot.delete_message(chat_id, message_id)

        # Cancel the active timer task
        active_timers[chat_id]["task"].cancel()

        # Remove the active timer variables for the specific channel
        del active_timers[chat_id]


@dp.message_handler(state=TimerStates.SETTING_TIMER)
async def confirm_timer(message: types.Message, state: FSMContext):
    confirmation = message.text.lower()
    if confirmation == "yes":
        data = await state.get_data()
        duration = data.get("duration")
        text = data.get("text")
        chat_id = message.chat.id

        # Check if there is an active timer in the channel
        if chat_id in active_timers:
            await message.reply(
                "A timer is already running in this channel. You cannot set a new timer."
            )
        else:
            # Save the active timer for the channel
            active_timers[chat_id] = {
                "task": asyncio.create_task(run_timer(duration, text, chat_id)),
                "last_message": None,  # Initialize last_message field
            }

            sent_message = await message.reply(
                f"Success! Timer {text} set for {duration} seconds."
            )

            # Pin the message to the top of the channel
            await asyncio.gather(
                send_timer_update(chat_id, sent_message.message_id, duration, text),
                pin_timer_message(chat_id, sent_message.message_id, duration),
            )

            # Update last_message information
            active_timers[chat_id]["last_message"] = {
                "message_id": sent_message.message_id,
            }

            # Reset the state after the timer is set or if there's an existing timer
            await state.finish()
        await state.finish()
    elif confirmation == "no":
        await message.reply("Timer setting canceled.")
        await state.finish()
    else:
        await message.reply("Please respond with 'yes' or 'no'.")
        await state.finish()

@dp.message_handler(commands=["canceltimer"])
async def cancel_timer_command(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    print('hi!')

    # Check if there is an active timer in the channel
    if chat_id in active_timers:
        await cancel_timer(chat_id)
        await state.finish()
        await message.reply(
            "Current timer canceled. You can now set a new countdown timer using /setcountdowntimer."
        )
    else:
        await message.reply("There is no active timer to cancel.")

from aiogram.types import ChatMember

@dp.message_handler(commands=["clear"])
async def clear_bot_messages_command(message: types.Message):
    chat_id = message.chat.id

    # Get information about the chat
    chat = await bot.get_chat(chat_id)

    # Get a list of administrators in the chat
    administrators = await bot.get_chat_administrators(chat_id)

    # Get the bot's user ID
    bot_user_id = (await bot.me).id

    # Iterate through the administrators and delete messages sent by the bot
    for admin in administrators:
        if admin.user.id == bot_user_id:
            continue  # Skip the bot itself
        admin_chat_member = await bot.get_chat_member(chat_id, admin.user.id)
        if admin_chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.CREATOR]:
            # User is an administrator or creator, delete their messages
            async for admin_message in bot.get_chat_history(chat_id, from_user=admin.user.id):
                await bot.delete_message(chat_id, admin_message.message_id)

    await message.reply("All bot messages have been cleared.")

if __name__ == "__main__":
    print("Bot is running.")
    executor.start_polling(dp, skip_updates=True)


if __name__ == "__main__":
    print("Bot is running.")
    executor.start_polling(dp, skip_updates=True)
