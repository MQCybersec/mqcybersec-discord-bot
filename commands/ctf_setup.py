import discord
from discord.ext import commands
import logging
from datetime import datetime
import re
from util import fetch_ics, parse_ics, fetch_event_image
from db import save_reaction_role, get_team_info, save_team_info, get_team_members, add_team_member, remove_team_member, remove_empty_team, get_available_team_slot

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
        add_texit_bot: bool = True,
        enable_team_limits: bool = False,
        team_size: int = 4
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
        logger.info(f"CTF Setup Parameters: ctf_url={ctf_url}, ctf_name={ctf_name}, enable_team_limits={enable_team_limits}, team_size={team_size}")
        
        try:
            if not interaction.user.guild_permissions.manage_roles:
                await interaction.response.send_message("You don't have permission to manage roles!", ephemeral=True)
                return

            # Validate team size
            if enable_team_limits and (team_size < 1 or team_size > 20):
                await interaction.response.send_message("Team size must be between 1 and 20 members!", ephemeral=True)
                return

            await interaction.response.defer()
            
            # Determine if we're using CTFtime or custom CTF setup
            using_ctftime = ctf_url is not None and ctf_url.startswith('https://ctftime.org/event/')
            using_custom = ctf_name is not None
            
            logger.info(f"CTF Type Detection: using_ctftime={using_ctftime}, using_custom={using_custom}")
            
            if not using_ctftime and not using_custom:
                logger.error("No CTF source provided (neither CTFtime URL nor custom name)")
                await interaction.followup.send("Please provide either a CTFtime URL or a custom CTF name.")
                return
            
            if using_ctftime and using_custom:
                logger.error("Both CTFtime URL and custom name provided")
                await interaction.followup.send("Please provide either a CTFtime URL or a custom CTF name, not both.")
                return
            
            event_info = None
            event_image = None
            
            # Process CTFtime event
            if using_ctftime:
                logger.info(f"Processing CTFtime event from URL: {ctf_url}")
                try:
                    ics_data = await fetch_ics(ctf_url)
                    event_info = parse_ics(ics_data)
                    event_image = await fetch_event_image(ctf_url)
                    url = ctf_url
                    ctf_name = event_info['name']
                    ctf_url = event_info['url'] or ctf_url
                    logger.info(f"CTFtime event processed successfully: {ctf_name}")
                except Exception as e:
                    logger.error(f"Error processing CTFtime event: {str(e)}")
                    await interaction.followup.send(f"Error processing CTFtime event: {str(e)}")
                    return
            # Process custom CTF
            else:
                logger.info(f"Processing custom CTF: {ctf_name}")
                try:
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
                                logger.info(f"Parsed start time: {start_dt}")
                        except Exception as e:
                            logger.warning(f"Could not parse start time '{start_time}': {str(e)}")
                    
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
                                logger.info(f"Parsed end time: {end_dt}")
                        except Exception as e:
                            logger.warning(f"Could not parse end time '{end_time}': {str(e)}")
                    
                    # Create event info dict
                    event_info = {
                        'name': ctf_name,
                        'url': custom_url,
                        'start': start_timestamp,
                        'end': end_timestamp
                    }
                    
                    url = custom_url
                    logger.info(f"Custom CTF processed successfully: {ctf_name}")
                except Exception as e:
                    logger.error(f"Error processing custom CTF: {str(e)}")
                    await interaction.followup.send(f"Error processing custom CTF: {str(e)}")
                    return

            # Create or get category
            current_year = datetime.now().year
            category_name = f"{current_year} CTFs"
            category = discord.utils.get(interaction.guild.categories, name=category_name)
            
            logger.info(f"Looking for category: {category_name}")
            if not category:
                logger.info(f"Creating new category: {category_name}")
                try:
                    category = await interaction.guild.create_category(
                        name=category_name,
                        reason="Created for CTF organization"
                    )
                    logger.info(f"Successfully created category: {category_name} (ID: {category.id})")
                except Exception as e:
                    logger.error(f"Error creating category: {str(e)}")
                    await interaction.followup.send(f"Error creating category: {str(e)}")
                    return
            else:
                logger.info(f"Using existing category: {category_name} (ID: {category.id})")

            # Create main event role (for team-based CTFs too)
            role_name = ctf_name.lower()
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            logger.info(f"Looking for existing role: {role_name}")
            if not role:
                logger.info(f"Creating new role: {role_name}")
                try:
                    role = await interaction.guild.create_role(
                        name=role_name,
                        reason="Created for CTF participation"
                    )
                    logger.info(f"Successfully created role: {role_name} (ID: {role.id})")
                except Exception as e:
                    logger.error(f"Error creating role: {str(e)}")
                    await interaction.followup.send(f"Error creating role: {str(e)}")
                    return
            else:
                logger.info(f"Using existing role: {role_name} (ID: {role.id})")

            # Create main channel
            channel_name = ctf_name.lower().replace(' ', '-')
            # Remove any special characters that Discord doesn't allow in channel names
            channel_name = re.sub(r'[^a-zA-Z0-9_-]', '', channel_name)
            
            existing_channel = discord.utils.get(category.channels, name=channel_name)
            ctf_channel = existing_channel
            
            if not existing_channel:
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(
                        read_messages=False,
                        send_messages=False
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
            
            # Create description based on whether we have timestamps and team limits
            if event_info['start'] and event_info['end']:
                if enable_team_limits:
                    description = f"Click the :white_check_mark: to join the CTF! (Teams of {team_size})\nRunning from <t:{event_info['start']}:F> to <t:{event_info['end']}:F>"
                else:
                    description = f"Click the :white_check_mark: if you will play, running from <t:{event_info['start']}:F> to <t:{event_info['end']}:F>"
            else:
                if enable_team_limits:
                    description = f"Click the :white_check_mark: to join the CTF! (Teams of {team_size})"
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

            if enable_team_limits:
                embed.add_field(
                    name="Team Registration",
                    value=f"React with ✅ to get the {role.mention} role and access to the main CTF channel. Teams of {team_size} will be created automatically and you'll get access to your team channel.",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Role",
                    value=f"React with ✅ to get the {role.mention} role and access to the CTF channel",
                    inline=False
                )

            if event_info['url'] and event_info['url'] != "N/A":
                embed.add_field(name="CTF URL", value=event_info['url'], inline=False)

            # Create the ping content if a role was specified
            ping_content = ""
            if pinged_role:
                ping_content = f"{pinged_role.mention} "
            
            # Send the announcement with optional ping
            reaction_message = await target_channel.send(content=ping_content, embed=embed)
            await reaction_message.add_reaction('✅')
            
            # Store the reaction message channel ID for later retrieval
            reaction_message_channel_id = target_channel.id
            logger.info(f"Reaction message posted in channel {target_channel.name} (ID: {reaction_message_channel_id})")

            # Create channel welcome embed
            if event_info['start'] and event_info['end']:
                channel_description = f'Running from <t:{event_info["start"]}:F> to <t:{event_info["end"]}:F>'
            else:
                channel_description = f'Welcome to the {ctf_name} CTF!'
                
            if enable_team_limits:
                channel_description += f'\n\nThis CTF uses team limits of {team_size} members. Teams and channels will be created automatically as players register.'
                
            channel_embed = discord.Embed(
                title=ctf_name,
                description=channel_description,
                color=discord.Color.blue(),
                url=url
            )
            
            if event_image:
                channel_embed.set_thumbnail(url=event_image)
            
            if event_info['url'] and event_info['url'] != "N/A":
                channel_embed.add_field(name="CTF URL", value=event_info['url'], inline=False)
            
            await ctf_channel.send(embed=channel_embed)

            # Save reaction role with team info and IMPORTANT: store reaction message channel ID
            if enable_team_limits:
                logger.info("Setting up team-based CTF with reaction role")
                try:
                    # Pass reaction_message_channel_id as the channel parameter for the reaction message location
                    save_reaction_role(reaction_message.id, role.id, '✅', ctf_channel.id, reaction_message_channel_id)
                    # Save team configuration
                    team_config = {
                        'ctf_name': ctf_name,
                        'team_size': team_size,
                        'category_id': category.id,
                        'guild_id': interaction.guild.id,
                        'add_texit_bot': add_texit_bot,
                        'event_role_id': role.id  # Store the main event role
                    }
                    save_team_info(reaction_message.id, team_config)
                    
                    bot.reaction_roles[reaction_message.id] = {
                        'role_id': role.id,
                        'emoji': '✅',
                        'channel_id': ctf_channel.id,
                        'reaction_message_channel_id': reaction_message_channel_id,  # Store both IDs
                        'team_config': team_config
                    }
                    logger.info(f"Successfully saved team configuration for message {reaction_message.id} in channel {reaction_message_channel_id}")
                except Exception as e:
                    logger.error(f"Error saving team configuration: {str(e)}")
                    await interaction.followup.send(f"Error saving team configuration: {str(e)}")
                    return
            else:
                logger.info("Setting up traditional CTF with single role")
                try:
                    # Pass reaction_message_channel_id for the reaction message location
                    save_reaction_role(reaction_message.id, role.id, '✅', ctf_channel.id, reaction_message_channel_id)
                    bot.reaction_roles[reaction_message.id] = {
                        'role_id': role.id,
                        'emoji': '✅',
                        'channel_id': ctf_channel.id,
                        'reaction_message_channel_id': reaction_message_channel_id  # Store both IDs
                    }
                    logger.info(f"Successfully saved reaction role for message {reaction_message.id} in channel {reaction_message_channel_id}")
                except Exception as e:
                    logger.error(f"Error saving reaction role: {str(e)}")
                    await interaction.followup.send(f"Error saving reaction role: {str(e)}")
                    return

            # Send success message
            if enable_team_limits:
                success_message = f"Setup complete!\n- Team-based CTF created with team size limit of {team_size}\n- Main channel: {ctf_channel.mention}\n- Teams will be created automatically as players register\n- Reaction role message posted in {target_channel.mention}"
            else:
                success_message = f"Setup complete!\n- Created role: {role.mention}\n- Created channel: {ctf_channel.mention}\n- Reaction role message posted in {target_channel.mention}"
            
            if pinged_role:
                success_message += f"\n- Pinged role: {pinged_role.mention}"
                
            await interaction.followup.send(success_message, ephemeral=True)
            logger.info(f"CTF setup successful for {ctf_name} by {interaction.user.name}#{interaction.user.discriminator} (Team limits: {enable_team_limits})")
        except Exception as e:
            logger.error(f"Error in setupctf command: {str(e)}", exc_info=True)
            await interaction.followup.send(f"Error setting up CTF: {str(e)}", ephemeral=True)

    # Function to handle team creation when reaction is added
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

    # Function to handle team reaction removal
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
            if team_role:
                member = guild.get_member(user.id)
                if member:
                    try:
                        await member.remove_roles(team_role)
                        logger.info(f"Removed team role {team_role_name} from user {user.id}")
                        # Note: We keep the event role so they still have access to main channel
                    except Exception as e:
                        logger.error(f"Error removing role {team_role_name} from user {user.id}: {str(e)}")
                else:
                    logger.warning(f"Could not find member {user.id} in guild to remove role")
            else:
                logger.warning(f"Could not find team role {team_role_name}")
            
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