import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from db import save_reaction_role, remove_reaction_role, load_reaction_roles, setup_database
from util import fetch_ics, fetch_event_image, parse_ics, get_weekend_ctfs
import logging
from logging.handlers import RotatingFileHandler

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
TOKEN = os.getenv('TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

import traceback
from typing import List, Dict, Optional, Set
from discord import Permissions

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


# COMMANDS

@bot.tree.command(name="ctfinfo", description="Get details about a CTF time event", guild=discord.Object(id=GUILD_ID))
async def ctftime(interaction: discord.Interaction, url: str):
    required_permissions = ['view_channel', 'send_messages', 'embed_links']
    
    # Check permissions
    perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
    missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
    
    if missing_perms:
        logger.error(f"Missing permissions for ctfinfo command: {', '.join(missing_perms)}")
        await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
        return

    logger.info(f"Command 'ctfinfo' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
    await interaction.response.defer()
    
    try:
        if not url.startswith('https://ctftime.org/event/'):
            await interaction.followup.send("Please provide a valid CTFtime event URL")
            return

        ics_data = await fetch_ics(url)
        event_info = parse_ics(ics_data)
        event_image = await fetch_event_image(url)

        embed = discord.Embed(
            title=event_info['name'],
            url=url,
            description=f"Running from <t:{event_info['start']}:F> to <t:{event_info['end']}:F>",
            color=discord.Color.blue()
        )
        
        if event_image:
            embed.set_thumbnail(url=event_image)
        
        if event_info['url']:
            embed.add_field(name="CTF URL", value=event_info['url'], inline=False)

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error processing event: {str(e)}")

@bot.tree.command(
    name="setupctf",
    description="Setup channels and roles for a CTF from CTFtime",
    guild=discord.Object(id=GUILD_ID)
)
async def setup_ctf(
    interaction: discord.Interaction,
    url: str,
    channel: discord.TextChannel = None
):
    required_permissions = [
        'manage_roles', 'manage_channels', 'view_channel', 
        'send_messages', 'embed_links', 'add_reactions',
        'create_public_threads', 'send_messages_in_threads'
    ]
    
    # Check permissions
    perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
    missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
    
    if missing_perms:
        logger.error(f"Missing permissions for setupctf command: {', '.join(missing_perms)}")
        await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
        return

    logger.info(f"Command 'setupctf' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
    try:
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("You don't have permission to manage roles!", ephemeral=True)
            return

        await interaction.response.defer()

        if not url.startswith('https://ctftime.org/event/'):
            await interaction.followup.send("Please provide a valid CTFtime event URL")
            return

        ics_data = await fetch_ics(url)
        event_info = parse_ics(ics_data)
        event_image = await fetch_event_image(url)

        current_year = datetime.now().year
        category_name = f"{current_year} CTFs"
        category = discord.utils.get(interaction.guild.categories, name=category_name)
        
        if not category:
            category = await interaction.guild.create_category(
                name=category_name,
                reason="Created for CTF organization"
            )

        role_name = event_info['name'].lower()
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            role = await interaction.guild.create_role(
                name=role_name,
                reason="Created for CTF participation"
            )

        channel_name = role_name.replace(' ', '-')
        existing_channel = discord.utils.get(category.channels, name=channel_name)
        if not existing_channel:
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(
                    read_messages=False
                ),
                role: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    create_public_threads=True,
                    send_messages_in_threads=True
                ),
                interaction.guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    read_messages=True,
                    send_messages=True,
                    create_public_threads=True,
                    send_messages_in_threads=True,
                    embed_links=True,
                    attach_files=True,
                    add_reactions=True,
                    manage_messages=True
                )
            }
            ctf_channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )

        target_channel = channel if channel else interaction.channel
        embed = discord.Embed(
            title=event_info['name'],
            description=f"Click the :white_check_mark: if you will play, running from <t:{event_info['start']}:F> to <t:{event_info['end']}:F>",
            color=discord.Color.blue(),
            url=url
        )

        if event_image:
            embed.set_thumbnail(url=event_image)

        embed.add_field(
            name="Role",
            value=f"React with ✅ to get the {role.mention} role and access to the CTF channel",
            inline=False
        )

        if event_info['url']:
            embed.add_field(name="CTF URL", value=event_info['url'], inline=False)

        reaction_message = await target_channel.send(embed=embed)
        await reaction_message.add_reaction('✅')

        embed = discord.Embed(
            title=event_info['name'],
            description=f'Running from <t:{event_info['start']}:F> to <t:{event_info['end']}:F>',
            color=discord.Color.blue(),
            url=url
        )
        if event_image:
            embed.set_thumbnail(url=event_image)
        
        if event_info['url']:
            embed.add_field(name="CTF URL", value=event_info['url'], inline=False)
        
        await ctf_channel.send(embed=embed)

        save_reaction_role(reaction_message.id, role.id, '✅')
        bot.reaction_roles[reaction_message.id] = {
            'role_id': role.id,
            'emoji': '✅'
        }

        success_message = f"Setup complete!\n- Created role: {role.mention}\n- Created channel: {ctf_channel.mention}\n- Reaction role message posted in {target_channel.mention}"
        await interaction.followup.send(success_message, ephemeral=True)
        logger.info(f"CTF setup successful for {event_info['name']} by {interaction.user.name}#{interaction.user.discriminator}")
    except Exception as e:
        logger.error(f"Error in setupctf command: {str(e)}")
        await interaction.followup.send(f"Error setting up CTF: {str(e)}", ephemeral=True)

@bot.tree.command(
    name="publishctf",
    description="Publish a CTF channel and make it read-only",
    guild=discord.Object(id=GUILD_ID)
)
async def publish_ctf(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    visible_role: discord.Role = None
):
    required_permissions = ['manage_roles', 'manage_channels', 'view_channel', 'send_messages']
    
    # Check permissions
    perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
    missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
    
    if missing_perms:
        logger.error(f"Missing permissions for publishctf command: {', '.join(missing_perms)}")
        await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
        return

    logger.info(f"Command 'publishctf' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
    try:
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("You don't have permission to manage roles!", ephemeral=True)
            return

        await interaction.response.defer()

        base_name = channel.name.replace('-', ' ').split(' ')[0]
        matching_roles = [r for r in interaction.guild.roles if r.name.lower().startswith(base_name.lower())]
        
        if not matching_roles:
            await interaction.followup.send(f"Could not find any roles starting with '{base_name}'!", ephemeral=True)
            return
            
        role = matching_roles[0]
        if len(matching_roles) > 1:
            channel_words = set(channel.name.replace('-', ' ').lower().split())
            best_match_score = 0
            
            for r in matching_roles:
                role_words = set(r.name.lower().split())
                match_score = len(channel_words.intersection(role_words))
                if match_score > best_match_score:
                    best_match_score = match_score
                    role = r

        view_role = visible_role if visible_role else interaction.guild.default_role
        
        new_overwrites = {
            view_role: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=False,
                create_public_threads=False,
                send_messages_in_threads=False
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                create_public_threads=True,
                send_messages_in_threads=True
            )
        }

        await channel.edit(overwrites=new_overwrites)

        await role.delete()

        to_remove = []
        for message_id, role_info in bot.reaction_roles.items():
            if role_info['role_id'] == role.id:
                to_remove.append(message_id)
                remove_reaction_role(message_id)

        for message_id in to_remove:
            bot.reaction_roles.pop(message_id, None)

        await interaction.followup.send(
            f"CTF published!\n"
            f"- Channel {channel.mention} is now visible to {view_role.mention}\n"
            f"- Role '{role.name}' has been deleted\n"
            f"- Channel is now read-only",
            ephemeral=True
        )
        logger.info(f"CTF channel {channel.name} published by {interaction.user.name}#{interaction.user.discriminator}")
    except Exception as e:
        logger.error(f"Error in publishctf command: {str(e)}")
        await interaction.followup.send(f"Error publishing CTF: {str(e)}", ephemeral=True)

@bot.tree.command(
    name="weekendctfs",
    description="Show CTFs happening this weekend",
    guild=discord.Object(id=GUILD_ID)
)
async def weekend_ctfs(interaction: discord.Interaction):
    required_permissions = ['view_channel', 'send_messages', 'embed_links']
    
    # Check permissions
    perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
    missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
    
    if missing_perms:
        logger.error(f"Missing permissions for weekendctfs command: {', '.join(missing_perms)}")
        await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
        return

    logger.info(f"Command 'weekendctfs' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
    try:
        await interaction.response.defer()
        
        ctfs = await get_weekend_ctfs(logger)
        
        if not ctfs:
            await interaction.followup.send("No CTFs found for this weekend!")
            return
            
        # Get next weekend's dates for the title
        today = datetime.now()
        saturday = today + timedelta(days=(5-today.weekday()) % 7)
        sunday = saturday + timedelta(days=1)
        weekend_str = f"{saturday.strftime('%B %d')} - {sunday.strftime('%B %d')}"
        
        embed = discord.Embed(
            title=f"CTFs This Weekend ({weekend_str})",
            color=discord.Color.blue(),
            description="Here are the upcoming CTFs for this weekend:"
        )
        
        # Display first 3 CTFs
        for i, ctf in enumerate(ctfs[:3], 1):
            embed.add_field(
                name=f"{i}. {ctf['name']}",
                value=f"Format: {ctf['format']}\n"
                      f"Teams Registered: {ctf['teams']}\n"
                      f"Weight: {ctf['weight']}\n"
                      f"[CTFtime Link]({ctf['url']})",
                inline=False
            )
        
        # Add note about additional CTFs if there are more
        if len(ctfs) > 3:
            remaining = len(ctfs) - 3
            embed.add_field(
                name="More CTFs",
                value=f"*{remaining} more CTFs not listed. [View all on CTFtime](https://ctftime.org/event/list/upcoming)*",
                inline=False
            )
            
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Error in weekend command: {str(e)}")
        await interaction.followup.send(f"Error fetching weekend CTFs: {str(e)}")

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
        setup_database()
        bot.reaction_roles = load_reaction_roles()
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

@bot.tree.command(
    name="solved",
    description="Mark the current thread as solved",
    guild=discord.Object(id=GUILD_ID)
)
async def solved(interaction: discord.Interaction):
    try:
        # Check if we're in a thread
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This command can only be used in a thread!", ephemeral=True)
            return

        thread = interaction.channel
        parent_channel = thread.parent
        
        # Check if the parent channel is in a category
        if not parent_channel.category:
            await interaction.response.send_message("This thread's channel is not in a category!", ephemeral=True)
            return
            
        # Check if the category is the current year's CTF category
        current_year = datetime.now().year
        if not parent_channel.category.name == f"{current_year} CTFs":
            await interaction.response.send_message(
                f"This command can only be used in threads within the '{current_year} CTFs' category!", 
                ephemeral=True
            )
            return

        # Log permissions for debugging
        thread_perms = thread.permissions_for(interaction.guild.me)
        parent_perms = parent_channel.permissions_for(interaction.guild.me)
        logger.info(f"Thread permissions: {thread_perms.value}")
        logger.info(f"Parent permissions: {parent_perms.value}")

        # Try to join the thread first
        try:
            await thread.join()
        except Exception as e:
            logger.error(f"Failed to join thread: {e}")

        # Check if we can manage threads
        if not thread_perms.manage_threads:
            await interaction.response.send_message(
                "Bot does not have permission to manage threads!", 
                ephemeral=True
            )
            return

        current_name = thread.name
        if current_name.startswith('[SOLVED] '):
            await interaction.response.send_message("This thread is already marked as solved!", ephemeral=True)
            return
            
        new_name = current_name.replace('[SOLVED]', '').strip()
        new_name = f'[SOLVED] {new_name}'

        try:
            # Try to update the thread name
            await thread.edit(
                name=new_name,
                reason=f"Marked as solved by {interaction.user.name}"
            )
            await interaction.response.send_message("Thread marked as solved!")
            logger.info(f"Thread '{current_name}' marked as solved by {interaction.user.name}#{interaction.user.discriminator}")
        except discord.Forbidden:
            # If we get a Forbidden error, try to join the thread first and then retry
            try:
                await thread.join()
                await thread.edit(
                    name=new_name,
                    reason=f"Marked as solved by {interaction.user.name}"
                )
                await interaction.response.send_message("Thread marked as solved!")
                logger.info(f"Thread '{current_name}' marked as solved by {interaction.user.name}#{interaction.user.discriminator} (after joining)")
            except Exception as e:
                raise Exception(f"Failed to edit thread even after joining: {str(e)}")
        
    except Exception as e:
        error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        logger.error(f"Error in solved command:\n{error_traceback}")
        await interaction.response.send_message(
            f"Error marking thread as solved. Please make sure the bot has the necessary permissions and is a member of the thread.",
            ephemeral=True
        )

bot.run(TOKEN)
