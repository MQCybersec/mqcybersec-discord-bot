import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import traceback
from typing import List, Dict
from discord import Permissions

from db import save_reaction_role, remove_reaction_role, load_reaction_roles, setup_database
from commands import setup_commands

def setup_logging():
    os.makedirs('logs', exist_ok=True)

    logger = logging.getLogger('discord_bot')
    logger.setLevel(logging.INFO)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    
    file_handler = RotatingFileHandler(
        'logs/discord.log',
        maxBytes=5*1024*1024,
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_format)
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

load_dotenv()
# print(os.environ)
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

def check_permissions(guild: discord.Guild, bot_member: discord.Member, required_permissions: List[str]) -> Dict[str, bool]:
    """
    Check if the bot has the required permissions in the guild
    Returns a dictionary of permission name to boolean indicating if the bot has that permission
    """
    permission_mapping = {
        'manage_roles': Permissions.manage_roles,
        'manage_channels': Permissions.manage_channels,
        'view_channel': Permissions.view_channel,
        'send_messages': Permissions.send_messages,
        'embed_links': Permissions.embed_links,
        'attach_files': Permissions.attach_files,
        'add_reactions': Permissions.add_reactions,
        'use_external_emojis': Permissions.use_external_emojis,
        'manage_messages': Permissions.manage_messages,
        'read_message_history': Permissions.read_message_history,
        'mention_everyone': Permissions.mention_everyone,
        'create_public_threads': Permissions.create_public_threads,
        'send_messages_in_threads': Permissions.send_messages_in_threads,
    }
    
    results = {}
    for perm in required_permissions:
        if perm in permission_mapping:
            has_perm = bot_member.guild_permissions.value & permission_mapping[perm].flag != 0
            results[perm] = has_perm
    
    return results

# EVENTS

@bot.event
async def on_raw_reaction_add(payload):
    try:
        if payload.message_id in bot.reaction_roles:
            role_info = bot.reaction_roles[payload.message_id]
            if str(payload.emoji) == role_info['emoji']:
                guild = bot.get_guild(payload.guild_id)
                role = guild.get_role(role_info['role_id'])
                member = guild.get_member(payload.user_id)
                
                if member and not member.bot:
                    logger.info(f"Reaction added by {member.name}#{member.discriminator} (ID: {member.id}) for message {payload.message_id}")
                    await member.add_roles(role)
    except Exception as e:
        error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        logger.error(f"Error in on_raw_reaction_add:\n{error_traceback}")


@bot.event
async def on_raw_reaction_remove(payload):
    try:
        if payload.message_id in bot.reaction_roles:
            role_info = bot.reaction_roles[payload.message_id]
            if str(payload.emoji) == role_info['emoji']:
                guild = bot.get_guild(payload.guild_id)
                role = guild.get_role(role_info['role_id'])
                member = guild.get_member(payload.user_id)
                
                if member and not member.bot:
                    logger.info(f"Reaction removed by {member.name}#{member.discriminator} (ID: {member.id}) for message {payload.message_id}")
                    await member.remove_roles(role)
    except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in on_raw_reaction_remove:\n{error_traceback}")

@bot.event
async def on_ready():
    try:
        # Setup database and load reaction roles
        setup_database()
        bot.reaction_roles = load_reaction_roles()
        
        # Setup commands
        setup_commands(bot, GUILD_ID, check_permissions)
        
        # Sync commands with Discord
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        
        logger.info(f'Bot logged in as {bot.user}')
        logger.info(f'Loaded {len(bot.reaction_roles)} reaction roles from database')
        
        # Check all required permissions on startup
        guild = bot.get_guild(GUILD_ID)
        if guild:
            all_permissions = [
                'manage_roles', 'manage_channels', 'view_channel', 
                'send_messages', 'embed_links', 'add_reactions',
                'use_external_emojis', 'manage_messages', 'read_message_history',
                'create_public_threads', 'send_messages_in_threads'
            ]
            
            perm_check = check_permissions(guild, guild.me, all_permissions)
            missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
            
            if missing_perms:
                logger.warning(f"Bot is missing the following permissions: {', '.join(missing_perms)}")
            else:
                logger.info("All required permissions are granted")
    except Exception as e:
        error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        logger.error(f"Error in on_ready:\n{error_traceback}")

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)