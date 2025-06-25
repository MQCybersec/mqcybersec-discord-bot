# Key changes needed in the main bot.py file:

# 1. Update the load_reaction_roles call to include reaction_message_channel_id
# In the load_reaction_roles function in db.py, we already handle this

# 2. Update the bot memory storage to include reaction_message_channel_id
# This is already handled in the setup_ctf.py updates

# 3. No major changes needed to bot.py since the reaction message channel ID
#    is primarily used by the convert commands to find the message

# However, here's a complete example of how the bot.py file should handle the new field:

import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import traceback
import re
from typing import List, Dict
from discord import Permissions

from db import (save_reaction_role, remove_reaction_role, load_reaction_roles, setup_database,
                get_team_members, add_team_member, remove_team_member, remove_empty_team, 
                get_available_team_slot, get_reaction_message_channel)
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

# Team handling functions (moved from setup_ctf.py to avoid import issues)
async def handle_team_reaction_add(reaction, user):
    """Handle reaction add for team-based CTFs"""
    if user.bot:
        return
        
    message_id = reaction.message.id
    if message_id not in bot.reaction_roles:
        return
        
    reaction_data = bot.reaction_roles[message_id]
    if 'team_config' not in reaction_data:
        return  # Not a team-based CTF
        
    team_config = reaction_data['team_config']
    guild = bot.get_guild(team_config['guild_id'])
    category = guild.get_channel(team_config['category_id'])
    
    try:
        # Check if user is already in a team for this CTF
        existing_team_info = get_team_members(message_id, user.id)
        if existing_team_info:
            # User already in a team, don't process
            logger.info(f"User {user.id} already in team {existing_team_info['team_number']} for CTF {team_config['ctf_name']}")
            return
        
        logger.info(f"Processing team reaction add for user {user.id} in CTF {team_config['ctf_name']}")
        
        # Find an available team slot using the improved logic
        available_team = get_available_team_slot(message_id, team_config['team_size'])
        
        # Add user to the available team
        success = add_team_member(message_id, available_team, user.id)
        if not success:
            logger.warning(f"Failed to add user {user.id} to team {available_team}")
            return
        
        # Get updated team member count
        team_members = get_team_members(message_id, team_number=available_team)
        team_member_count = len(team_members)
        logger.info(f"Team {available_team} now has {team_member_count}/{team_config['team_size']} members")
        
        # Check if we need to create/update the team role and channel
        team_role_name = f"{team_config['ctf_name'].lower()}-team-{available_team}"
        team_role = discord.utils.get(guild.roles, name=team_role_name)
        
        # Create role if it doesn't exist
        if not team_role:
            logger.info(f"Creating team role: {team_role_name}")
            try:
                team_role = await guild.create_role(
                    name=team_role_name,
                    reason=f"Created for CTF team {available_team}"
                )
                logger.info(f"Successfully created role {team_role_name} (ID: {team_role.id})")
            except Exception as e:
                logger.error(f"Error creating team role {team_role_name}: {str(e)}")
                raise
        else:
            logger.debug(f"Using existing team role: {team_role_name}")
        
        # Create channel if it doesn't exist
        team_channel_name = f"{team_config['ctf_name'].lower().replace(' ', '-')}-team-{available_team}"
        team_channel_name = re.sub(r'[^a-zA-Z0-9_-]', '', team_channel_name)
        team_channel = discord.utils.get(category.channels, name=team_channel_name)
        
        if not team_channel:
            logger.info(f"Creating team channel: {team_channel_name}")
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=False
                    ),
                    team_role: discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                        create_public_threads=True,
                        send_messages_in_threads=True
                    ),
                    guild.me: discord.PermissionOverwrite(
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
                
                # Add texit bot permissions if enabled
                if team_config.get('add_texit_bot', False):
                    texit_bot_id = 510789298321096704
                    texit_bot_member = guild.get_member(texit_bot_id)
                    if texit_bot_member:
                        overwrites[texit_bot_member] = discord.PermissionOverwrite(
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
                        logger.debug(f"Added Texit bot permissions to team channel")
                
                team_channel = await guild.create_text_channel(
                    name=team_channel_name,
                    category=category,
                    overwrites=overwrites
                )
                logger.info(f"Successfully created team channel {team_channel_name} (ID: {team_channel.id})")
                
                # Send initial welcome message for new channel
                team_embed = discord.Embed(
                    title=f"Team {available_team} - {team_config['ctf_name']}",
                    description=f"Welcome to Team {available_team}! This team can have up to {team_config['team_size']} members.",
                    color=discord.Color.blue()
                )
                await team_channel.send(embed=team_embed)
                logger.debug(f"Sent welcome message to new team channel")
            except Exception as e:
                logger.error(f"Error creating team channel {team_channel_name}: {str(e)}")
                raise
        else:
            logger.debug(f"Using existing team channel: {team_channel_name}")
        
        # Assign role to the new user (both event role and team role)
        member = guild.get_member(user.id)
        if member:
            try:
                # Give the main event role
                event_role_id = team_config.get('event_role_id')
                if event_role_id:
                    event_role = guild.get_role(event_role_id)
                    if event_role:
                        await member.add_roles(event_role)
                        logger.info(f"Added event role {event_role.name} to user {user.id}")
                
                # Give the team role
                await member.add_roles(team_role)
                logger.info(f"Added team role {team_role_name} to user {user.id}")
            except Exception as e:
                logger.error(f"Error adding roles to user {user.id}: {str(e)}")
                raise
        else:
            logger.error(f"Could not find member {user.id} in guild")
        
        # Update team status message in channel if team is full
        if team_member_count == team_config['team_size']:
            logger.info(f"Team {available_team} is now complete")
            # Get all team member mentions
            member_mentions = []
            for member_id in team_members:
                team_member = guild.get_member(member_id)
                if team_member:
                    member_mentions.append(team_member.mention)
            
            # Send team complete message
            complete_embed = discord.Embed(
                title=f"Team {available_team} Complete!",
                description=f"Team {available_team} is now full with {team_config['team_size']} members.",
                color=discord.Color.green()
            )
            complete_embed.add_field(
                name="Team Members",
                value="\n".join(member_mentions),
                inline=False
            )
            
            await team_channel.send(embed=complete_embed)
            logger.info(f"Team {available_team} completed for CTF {team_config['ctf_name']} with {team_member_count} members")
        else:
            # Send member joined message
            join_embed = discord.Embed(
                title=f"Member Joined Team {available_team}",
                description=f"{member.mention} joined the team! ({team_member_count}/{team_config['team_size']} members)",
                color=discord.Color.blue()
            )
            await team_channel.send(embed=join_embed)
            logger.info(f"User {user.id} joined team {available_team} for CTF {team_config['ctf_name']} ({team_member_count}/{team_config['team_size']})")
            
    except Exception as e:
        logger.error(f"Error handling team reaction add for user {user.id}: {str(e)}", exc_info=True)

async def handle_team_reaction_remove(reaction, user):
    """Handle reaction remove for team-based CTFs"""
    if user.bot:
        return
        
    message_id = reaction.message.id
    if message_id not in bot.reaction_roles:
        return
        
    reaction_data = bot.reaction_roles[message_id]
    if 'team_config' not in reaction_data:
        return  # Not a team-based CTF
        
    team_config = reaction_data['team_config']
    guild = bot.get_guild(team_config['guild_id'])
    
    try:
        # Check if user is in a team for this CTF
        user_team_info = get_team_members(message_id, user.id)
        if not user_team_info:
            logger.info(f"User {user.id} not in any team for CTF {team_config['ctf_name']}")
            return
            
        team_number = user_team_info['team_number']
        logger.info(f"Processing team reaction remove for user {user.id} from team {team_number} in CTF {team_config['ctf_name']}")
        
        # Remove user from team
        team_number = remove_team_member(message_id, user.id)
        if team_number is None:
            logger.warning(f"Could not determine team number for user {user.id}")
            return
        
        # Remove team role from user (keep event role)
        team_role_name = f"{team_config['ctf_name'].lower()}-team-{team_number}"
        team_role = discord.utils.get(guild.roles, name=team_role_name)
        
        # Also remove the event role for team-based CTFs
        event_role_id = team_config.get('event_role_id')
        event_role = guild.get_role(event_role_id) if event_role_id else None
        
        if team_role or event_role:
            member = guild.get_member(user.id)
            if member:
                try:
                    # Remove team role if it exists
                    if team_role:
                        await member.remove_roles(team_role)
                        logger.info(f"Removed team role {team_role_name} from user {user.id}")
                    
                    # Remove event role for team-based CTFs (complete CTF removal)
                    if event_role:
                        await member.remove_roles(event_role)
                        logger.info(f"Removed event role {event_role.name} from user {user.id}")
                        
                except Exception as e:
                    logger.error(f"Error removing roles from user {user.id}: {str(e)}")
            else:
                logger.warning(f"Could not find member {user.id} in guild to remove roles")
        else:
            logger.warning(f"Could not find team role {team_role_name} or event role")
        
        # Check if team is now empty and clean up if needed
        remaining_members = get_team_members(message_id, team_number=team_number)
        logger.info(f"Team {team_number} now has {len(remaining_members)} remaining members")
        
        if not remaining_members:  # Team is empty
            logger.info(f"Team {team_number} is empty, cleaning up...")
            
            # Delete the team channel
            category = guild.get_channel(team_config['category_id'])
            team_channel_name = f"{team_config['ctf_name'].lower().replace(' ', '-')}-team-{team_number}"
            team_channel_name = re.sub(r'[^a-zA-Z0-9_-]', '', team_channel_name)
            team_channel = discord.utils.get(category.channels, name=team_channel_name)
            
            if team_channel:
                try:
                    await team_channel.delete(reason=f"Team {team_number} is empty")
                    logger.info(f"Deleted empty team channel {team_channel_name}")
                except Exception as e:
                    logger.error(f"Error deleting team channel {team_channel_name}: {str(e)}")
            else:
                logger.warning(f"Could not find team channel {team_channel_name} to delete")
            
            # Delete the team role
            if team_role:
                try:
                    await team_role.delete(reason=f"Team {team_number} is empty")
                    logger.info(f"Deleted empty team role {team_role_name}")
                except Exception as e:
                    logger.error(f"Error deleting team role {team_role_name}: {str(e)}")
            
            # Clean up database records for the empty team
            try:
                remove_empty_team(message_id, team_number)
            except Exception as e:
                logger.error(f"Error cleaning up database for empty team {team_number}: {str(e)}")
        else:
            # Send member left message to team channel
            category = guild.get_channel(team_config['category_id'])
            team_channel_name = f"{team_config['ctf_name'].lower().replace(' ', '-')}-team-{team_number}"
            team_channel_name = re.sub(r'[^a-zA-Z0-9_-]', '', team_channel_name)
            team_channel = discord.utils.get(category.channels, name=team_channel_name)
            
            if team_channel:
                try:
                    member = guild.get_member(user.id)
                    leave_embed = discord.Embed(
                        title=f"Member Left Team {team_number}",
                        description=f"{member.mention if member else f'User {user.id}'} left the team. ({len(remaining_members)}/{team_config['team_size']} members)",
                        color=discord.Color.orange()
                    )
                    await team_channel.send(embed=leave_embed)
                    logger.debug(f"Sent member left message to team channel")
                except Exception as e:
                    logger.error(f"Error sending member left message: {str(e)}")
            else:
                logger.warning(f"Could not find team channel {team_channel_name} to send leave message")
                
        logger.info(f"Successfully removed user {user.id} from team {team_number} for CTF {team_config['ctf_name']}")
                    
    except Exception as e:
        logger.error(f"Error handling team reaction removal for user {user.id}: {str(e)}", exc_info=True)

# EVENTS
@bot.event
async def on_raw_reaction_add(payload):
    try:
        if payload.user_id == bot.user.id:  # Ignore bot's own reactions
            return
            
        if payload.message_id in bot.reaction_roles:
            role_info = bot.reaction_roles[payload.message_id]
            
            if str(payload.emoji) == role_info['emoji']:
                guild = bot.get_guild(payload.guild_id)
                member = guild.get_member(payload.user_id)
                
                if member and not member.bot:
                    logger.info(f"Reaction added by {member.name}#{member.discriminator} (ID: {member.id}) for message {payload.message_id}")
                    logger.info(f"Role info debug: {role_info}")
                    logger.info(f"Has team_config: {'team_config' in role_info}")
                    
                    # Check if this is a team-based CTF
                    if 'team_config' in role_info:
                        logger.info("Processing as team-based CTF")
                        # Get the message and reaction objects
                        channel = bot.get_channel(payload.channel_id)
                        message = await channel.fetch_message(payload.message_id)
                        reaction = discord.utils.get(message.reactions, emoji=payload.emoji.name)
                        
                        # Handle team-based reaction
                        await handle_team_reaction_add(reaction, member)
                    else:
                        logger.info("Processing as traditional CTF")
                        # Traditional CTF - assign role directly
                        role = guild.get_role(role_info['role_id'])
                        if role:
                            await member.add_roles(role)
                            logger.info(f"Added role {role.name} to {member.name}")
                        else:
                            logger.error(f"Role {role_info['role_id']} not found for message {payload.message_id}")
                            
    except Exception as e:
        error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        logger.error(f"Error in on_raw_reaction_add:\n{error_traceback}")

@bot.event
async def on_raw_reaction_remove(payload):
    try:
        if payload.user_id == bot.user.id:  # Ignore bot's own reactions
            return
            
        if payload.message_id in bot.reaction_roles:
            role_info = bot.reaction_roles[payload.message_id]
            if str(payload.emoji) == role_info['emoji']:
                guild = bot.get_guild(payload.guild_id)
                member = guild.get_member(payload.user_id)
                
                if member and not member.bot:
                    logger.info(f"Reaction removed by {member.name}#{member.discriminator} (ID: {member.id}) for message {payload.message_id}")
                    
                    # Check if this is a team-based CTF
                    if 'team_config' in role_info:
                        # Get the message and reaction objects
                        channel = bot.get_channel(payload.channel_id)
                        message = await channel.fetch_message(payload.message_id)
                        reaction = discord.utils.get(message.reactions, emoji=payload.emoji.name)
                        
                        # Handle team-based reaction removal
                        await handle_team_reaction_remove(reaction, member)
                    else:
                        # Traditional CTF - remove role directly
                        role = guild.get_role(role_info['role_id'])
                        if role:
                            await member.remove_roles(role)
                            logger.info(f"Removed role {role.name} from {member.name}")
                        else:
                            logger.error(f"Role {role_info['role_id']} not found for message {payload.message_id}")
                            
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
        
        # Log reaction roles with reaction message channel info
        for message_id, role_info in bot.reaction_roles.items():
            if 'reaction_message_channel_id' in role_info and role_info['reaction_message_channel_id']:
                logger.info(f"Message {message_id} has reaction message in channel {role_info['reaction_message_channel_id']}")
        
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