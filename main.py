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

# COMMANDS

@bot.tree.command(name="ctfinfo", description="Get details about a CTF time event", guild=discord.Object(id=GUILD_ID))
async def ctftime(interaction: discord.Interaction, url: str):
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
                    read_messages=True,
                    send_messages=True,
                    create_public_threads=True,
                    send_messages_in_threads=True
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
    logger.info(f"Command 'weekend' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
    
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
    if payload.message_id in bot.reaction_roles:
        role_info = bot.reaction_roles[payload.message_id]
        if str(payload.emoji) == role_info['emoji']:
            guild = bot.get_guild(payload.guild_id)
            role = guild.get_role(role_info['role_id'])
            member = guild.get_member(payload.user_id)
            
            if member and not member.bot:
                logger.info(f"Reaction added by {member.name}#{member.discriminator} (ID: {member.id}) for message {payload.message_id}")
                await member.add_roles(role)

@bot.event
async def on_raw_reaction_remove(payload):
    if payload.message_id in bot.reaction_roles:
        role_info = bot.reaction_roles[payload.message_id]
        if str(payload.emoji) == role_info['emoji']:
            guild = bot.get_guild(payload.guild_id)
            role = guild.get_role(role_info['role_id'])
            member = guild.get_member(payload.user_id)
            
            if member and not member.bot:
                logger.info(f"Reaction removed by {member.name}#{member.discriminator} (ID: {member.id}) for message {payload.message_id}")
                await member.remove_roles(role)

@bot.event
async def on_ready():
    setup_database()
    bot.reaction_roles = load_reaction_roles()
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    logger.info(f'Bot logged in as {bot.user}')
    logger.info(f'Loaded {len(bot.reaction_roles)} reaction roles from database')

bot.run(TOKEN)
