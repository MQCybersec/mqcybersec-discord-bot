import discord
from discord.ext import commands
import logging
from datetime import datetime
import re
from util import fetch_ics, parse_ics, fetch_event_image
from db import save_reaction_role

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_setup",
        description="Setup channels and roles for a CTF from CTFtime or a custom CTF",
        guild=discord.Object(id=guild_id)
    )
    async def setup_ctf(
        interaction: discord.Interaction,
        ctf_url: str = None,
        ctf_name: str = None,
        custom_url: str = None,
        channel: discord.TextChannel = None,
        start_time: str = None,
        end_time: str = None,
        pinged_role: discord.Role = None,
        add_texit_bot: bool = True
    ):
        required_permissions = [
            'manage_roles', 'manage_channels', 'view_channel', 
            'send_messages', 'embed_links', 'add_reactions',
            'create_public_threads', 'send_messages_in_threads'
        ]
        
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
            
            # Determine if we're using CTFtime or custom CTF setup
            using_ctftime = ctf_url is not None and ctf_url.startswith('https://ctftime.org/event/')
            using_custom = ctf_name is not None
            
            if not using_ctftime and not using_custom:
                await interaction.followup.send("Please provide either a CTFtime URL or a custom CTF name.")
                return
            
            if using_ctftime and using_custom:
                await interaction.followup.send("Please provide either a CTFtime URL or a custom CTF name, not both.")
                return
            
            event_info = None
            event_image = None
            
            # Process CTFtime event
            if using_ctftime:
                ics_data = await fetch_ics(ctf_url)
                event_info = parse_ics(ics_data)
                event_image = await fetch_event_image(ctf_url)
                url = ctf_url
                ctf_name = event_info['name']
                ctf_url = event_info['url'] or ctf_url
            # Process custom CTF
            else:
                if not custom_url:
                    custom_url = "N/A"
                
                # Process start and end times if provided
                start_timestamp = None
                end_timestamp = None
                
                if start_time:
                    try:
                        # Accept format like "YYYY-MM-DD HH:MM" or "YYYY-MM-DD"
                        start_pattern = r'(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?'
                        start_match = re.match(start_pattern, start_time)
                        
                        if start_match:
                            start_date = start_match.group(1)
                            start_hour = start_match.group(2) or "00:00"
                            start_dt = datetime.strptime(f"{start_date} {start_hour}", "%Y-%m-%d %H:%M")
                            start_timestamp = int(start_dt.timestamp())
                    except:
                        logger.warning(f"Could not parse start time: {start_time}")
                
                if end_time:
                    try:
                        # Accept format like "YYYY-MM-DD HH:MM" or "YYYY-MM-DD"
                        end_pattern = r'(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?'
                        end_match = re.match(end_pattern, end_time)
                        
                        if end_match:
                            end_date = end_match.group(1)
                            end_hour = end_match.group(2) or "23:59"
                            end_dt = datetime.strptime(f"{end_date} {end_hour}", "%Y-%m-%d %H:%M")
                            end_timestamp = int(end_dt.timestamp())
                    except:
                        logger.warning(f"Could not parse end time: {end_time}")
                
                # Create event info dict
                event_info = {
                    'name': ctf_name,
                    'url': custom_url,
                    'start': start_timestamp,
                    'end': end_timestamp
                }
                
                url = custom_url

            # Create or get category
            current_year = datetime.now().year
            category_name = f"{current_year} CTFs"
            category = discord.utils.get(interaction.guild.categories, name=category_name)
            
            if not category:
                category = await interaction.guild.create_category(
                    name=category_name,
                    reason="Created for CTF organization"
                )

            # Create role
            role_name = ctf_name.lower()
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            if not role:
                role = await interaction.guild.create_role(
                    name=role_name,
                    reason="Created for CTF participation"
                )

            # Create channel
            channel_name = role_name.replace(' ', '-')
            # Remove any special characters that Discord doesn't allow in channel names
            channel_name = re.sub(r'[^a-zA-Z0-9_-]', '', channel_name)
            
            existing_channel = discord.utils.get(category.channels, name=channel_name)
            ctf_channel = existing_channel
            
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
                
                # Check if add texit bot option is enabled and the bot is in the server
                if add_texit_bot:
                    texit_bot_id = 510789298321096704  # ID for texit bot
                    texit_bot_member = interaction.guild.get_member(texit_bot_id)
                    if texit_bot_member:
                        # Add texit bot to overwrites with same permissions as the current bot
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
                        logger.info(f"Added Texit bot permissions for channel {channel_name}")
                
                ctf_channel = await interaction.guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites
                )

            # Create reaction role embed
            target_channel = channel if channel else interaction.channel
            
            # Create description based on whether we have timestamps
            if event_info['start'] and event_info['end']:
                description = f"Click the :white_check_mark: if you will play, running from <t:{event_info['start']}:F> to <t:{event_info['end']}:F>"
            else:
                description = f"Click the :white_check_mark: if you will play in {ctf_name}."
            
            embed = discord.Embed(
                title=ctf_name,
                description=description,
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

            if event_info['url'] and event_info['url'] != "N/A":
                embed.add_field(name="ctf_URL", value=event_info['url'], inline=False)

            # Create the ping content if a role was specified
            ping_content = ""
            if pinged_role:
                ping_content = f"{pinged_role.mention} "
            
            # Send the announcement with optional ping
            reaction_message = await target_channel.send(content=ping_content, embed=embed)
            await reaction_message.add_reaction('✅')

            # Create channel welcome embed
            if event_info['start'] and event_info['end']:
                channel_description = f'Running from <t:{event_info["start"]}:F> to <t:{event_info["end"]}:F>'
            else:
                channel_description = f'Welcome to the {ctf_name} CTF channel!'
                
            channel_embed = discord.Embed(
                title=ctf_name,
                description=channel_description,
                color=discord.Color.blue(),
                url=url
            )
            
            if event_image:
                channel_embed.set_thumbnail(url=event_image)
            
            if event_info['url'] and event_info['url'] != "N/A":
                channel_embed.add_field(name="ctf_URL", value=event_info['url'], inline=False)
            
            await ctf_channel.send(embed=channel_embed)

            # Save reaction role
            save_reaction_role(reaction_message.id, role.id, '✅')
            bot.reaction_roles[reaction_message.id] = {
                'role_id': role.id,
                'emoji': '✅'
            }

            # Send success message
            success_message = f"Setup complete!\n- Created role: {role.mention}\n- Created channel: {ctf_channel.mention}\n- Reaction role message posted in {target_channel.mention}"
            
            if pinged_role:
                success_message += f"\n- Pinged role: {pinged_role.mention}"
                
            await interaction.followup.send(success_message, ephemeral=True)
            logger.info(f"CTF setup successful for {ctf_name} by {interaction.user.name}#{interaction.user.discriminator}")
        except Exception as e:
            logger.error(f"Error in setupctf command: {str(e)}")
            await interaction.followup.send(f"Error setting up CTF: {str(e)}", ephemeral=True)