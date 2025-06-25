import discord
from discord.ext import commands
import logging
import traceback
import re
import math
from typing import Optional
from db import (save_reaction_role, get_team_info, save_team_info, get_team_members, 
                add_team_member, remove_team_member, remove_empty_team, get_ctf_by_channel,
                get_reaction_message_channel)

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_converttoteams",
        description="Convert a traditional CTF with one large team into smaller teams with size limits",
        guild=discord.Object(id=guild_id)
    )
    async def convert_to_teams(
        interaction: discord.Interaction,
        team_size: int,
        channel: Optional[discord.TextChannel] = None
    ):
        """
        Convert a traditional CTF into a team-based CTF with smaller teams
        
        Parameters:
        -----------
        team_size: The new team size limit (1-20)
        channel: The CTF channel to convert (defaults to current channel)
        """
        required_permissions = [
            'manage_roles', 'manage_channels', 'view_channel', 
            'send_messages', 'embed_links', 'add_reactions',
            'create_public_threads', 'send_messages_in_threads'
        ]
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for converttoteams command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'converttoteams' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        logger.info(f"Convert to Teams Parameters: team_size={team_size}, channel={channel.name if channel else 'current'}")
        
        try:
            # Check if user has permission to manage roles
            if not interaction.user.guild_permissions.manage_roles:
                await interaction.response.send_message("You don't have permission to convert CTF teams!", ephemeral=True)
                return
            
            # Validate team size
            if team_size < 1 or team_size > 20:
                await interaction.response.send_message("Team size must be between 1 and 20 members!", ephemeral=True)
                return
            
            await interaction.response.defer()
            
            # Determine which channel to use
            target_channel = channel if channel else interaction.channel
            
            # Check if the channel is a CTF channel
            if not target_channel.category or not target_channel.category.name.endswith("CTFs"):
                await interaction.followup.send("This command can only be used in a CTF channel!", ephemeral=True)
                return
            
            logger.info(f"Looking up CTF by channel ID: {target_channel.id}")
            
            # Look up CTF directly by channel ID in database
            message_id = get_ctf_by_channel(target_channel.id)
            
            if not message_id:
                error_msg = "No CTF found for this channel in the database!\n\n"
                error_msg += "**Debugging info:**\n"
                error_msg += f"• Current channel: `{target_channel.name}` (ID: {target_channel.id})\n"
                error_msg += f"• Category: `{target_channel.category.name}`\n\n"
                error_msg += "**Possible reasons:**\n"
                error_msg += "• This CTF was created before channel tracking was implemented\n"
                error_msg += "• This channel is not the main CTF channel\n"
                error_msg += "• The CTF was set up differently\n\n"
                error_msg += "**Solution:**\n"
                error_msg += "Try running this command from the main CTF channel (where the reaction message is posted)."
                
                await interaction.followup.send(error_msg, ephemeral=True)
                return
            
            logger.info(f"Found CTF message {message_id} for channel {target_channel.id}")
            
            # Check if it's a traditional CTF
            if message_id not in bot.reaction_roles:
                await interaction.followup.send("CTF configuration not found in bot memory. Try restarting the bot.", ephemeral=True)
                return
            
            role_data = bot.reaction_roles[message_id]
            logger.info(f"Role data for message {message_id}: {role_data}")
            
            if 'team_config' in role_data:
                await interaction.followup.send("This CTF is already team-based! Use `/ctf_splitteams` instead to change team sizes.", ephemeral=True)
                return
            
            if role_data.get('role_id') is None:
                await interaction.followup.send("Invalid CTF configuration - no role found!", ephemeral=True)
                return
            
            # Get the role and message
            existing_role = interaction.guild.get_role(role_data['role_id'])
            if not existing_role:
                await interaction.followup.send("CTF role not found! The role may have been deleted.", ephemeral=True)
                return
            
            # We have everything we need from the database - no need to fetch the actual message
            logger.info(f"CTF found: message_id={message_id}, role={existing_role.name}")
            
            # Set the main channel as current channel (we'll update the message there)
            ctf_main_channel = target_channel
            
            if not existing_role:
                await interaction.followup.send("Could not find the existing CTF role! The role may have been deleted.", ephemeral=True)
                return
            
            # Get all members with the existing role
            members_with_role = [member for member in interaction.guild.members if existing_role in member.roles]
            logger.info(f"Found {len(members_with_role)} members with role {existing_role.name}")
            
            if len(members_with_role) == 0:
                await interaction.followup.send("No members found with the CTF role! Nothing to convert.", ephemeral=True)
                return
            
            # Get CTF info from the role and message ID (no need to fetch actual message)
            ctf_name = existing_role.name  # Use role name as CTF name
            ctf_url = "https://ctftime.org/"  # Default URL
            
            # Calculate how many teams we need
            num_teams = math.ceil(len(members_with_role) / team_size)
            logger.info(f"Will create {num_teams} teams of size {team_size} for {len(members_with_role)} members")
            
            # Get category and guild info
            category = target_channel.category
            guild = interaction.guild
            
            # Create team configuration
            team_config = {
                'ctf_name': ctf_name,
                'team_size': team_size,
                'category_id': category.id,
                'guild_id': guild.id,
                'add_texit_bot': True,  # Default to true, can be adjusted
                'event_role_id': existing_role.id
            }
            
            # Create teams and assign members
            team_assignments = []
            created_teams = []
            
            for team_num in range(1, num_teams + 1):
                start_idx = (team_num - 1) * team_size
                end_idx = min(start_idx + team_size, len(members_with_role))
                team_members = members_with_role[start_idx:end_idx]
                
                logger.info(f"Creating team {team_num} with {len(team_members)} members")
                
                # Add members to database
                for member in team_members:
                    add_team_member(message_id, team_num, member.id)
                
                # Create team role
                team_role_name = f"{ctf_name.lower()}-team-{team_num}"
                team_role = await guild.create_role(
                    name=team_role_name,
                    reason=f"Created for CTF team {team_num} during conversion"
                )
                
                # Create team channel
                team_channel_name = f"{ctf_name.lower().replace(' ', '-')}-team-{team_num}"
                team_channel_name = re.sub(r'[^a-zA-Z0-9_-]', '', team_channel_name)
                
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
                if team_config.get('add_texit_bot', True):
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
                
                team_channel = await guild.create_text_channel(
                    name=team_channel_name,
                    category=category,
                    overwrites=overwrites
                )
                
                # Assign team role to members but keep the existing event role
                member_mentions = []
                for member in team_members:
                    try:
                        # Add new team role (keep existing event role)
                        await member.add_roles(team_role)
                        member_mentions.append(member.mention)
                        logger.debug(f"Converted user {member.id} to team {team_num} (kept event role)")
                    except Exception as e:
                        logger.error(f"Error converting user {member.id}: {str(e)}")
                
                # Send welcome message to team channel
                team_embed = discord.Embed(
                    title=f"Team {team_num} - {ctf_name}",
                    description=f"Welcome to your new team! This CTF has been converted to use teams of {team_size} members each.",
                    color=discord.Color.green(),
                    url=ctf_url
                )
                team_embed.add_field(
                    name=f"Team Members ({len(team_members)}/{team_size})",
                    value="\n".join(member_mentions),
                    inline=False
                )
                
                await team_channel.send(embed=team_embed)
                
                team_assignments.append(f"Team {team_num}: {len(team_members)} members")
                created_teams.append(team_num)
            
            # Update the main channel permissions (event role can access, but only bot can post)
            try:
                await target_channel.edit(overwrites={
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=False,
                        send_messages=False
                    ),
                    existing_role: discord.PermissionOverwrite(
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
                })
                logger.info("Updated main channel permissions for team-based CTF")
            except Exception as e:
                logger.error(f"Error updating main channel permissions: {str(e)}")
            
            # Update the reaction role configuration in database and memory
            save_reaction_role(message_id, existing_role.id, '✅', target_channel.id, role_data.get('reaction_message_channel_id'))
            save_team_info(message_id, team_config)
            
            bot.reaction_roles[message_id] = {
                'role_id': existing_role.id,  # Keep the event role
                'emoji': '✅',
                'channel_id': target_channel.id,
                'reaction_message_channel_id': role_data.get('reaction_message_channel_id'),
                'team_config': team_config
            }
            
            logger.info("Updated reaction role configuration to team-based")
            
            # Don't delete the old role - it becomes the event role
            logger.info(f"Converted role {existing_role.name} to event role for team-based CTF")
            
            # Update the reaction message embed to reflect team-based nature
            try:
                # Get the reaction message channel ID from database
                reaction_message_channel_id = get_reaction_message_channel(message_id)
                reaction_message = None
                
                if reaction_message_channel_id:
                    logger.info(f"Found reaction message channel {reaction_message_channel_id} for message {message_id}")
                    reaction_message_channel = guild.get_channel(reaction_message_channel_id)
                    
                    if reaction_message_channel:
                        try:
                            reaction_message = await reaction_message_channel.fetch_message(message_id)
                            logger.info(f"Successfully found reaction message {message_id} in channel {reaction_message_channel.name}")
                        except discord.NotFound:
                            logger.warning(f"Reaction message {message_id} not found in expected channel {reaction_message_channel.name}")
                            reaction_message = None
                        except Exception as e:
                            logger.error(f"Error fetching reaction message {message_id}: {str(e)}")
                            reaction_message = None
                    else:
                        logger.warning(f"Reaction message channel {reaction_message_channel_id} not found")
                        reaction_message = None
                else:
                    logger.warning(f"No reaction message channel stored for message {message_id}, falling back to search")
                    # Fall back to searching all category channels if no stored channel
                    channels_searched = []
                    
                    for channel_to_search in target_channel.category.text_channels:
                        channels_searched.append(channel_to_search.name)
                        try:
                            reaction_message = await channel_to_search.fetch_message(message_id)
                            logger.info(f"Found reaction message {message_id} in channel {channel_to_search.name}")
                            # Update the database with the correct channel
                            save_reaction_role(message_id, existing_role.id, '✅', target_channel.id, channel_to_search.id)
                            bot.reaction_roles[message_id]['reaction_message_channel_id'] = channel_to_search.id
                            logger.info(f"Updated reaction message channel ID to {channel_to_search.id}")
                            break
                        except discord.NotFound:
                            logger.debug(f"Message {message_id} not found in {channel_to_search.name}")
                            continue
                        except discord.Forbidden:
                            logger.debug(f"No permission to read channel {channel_to_search.name}")
                            continue
                        except Exception as e:
                            logger.debug(f"Error searching {channel_to_search.name}: {str(e)}")
                            continue
                    
                    logger.info(f"Searched channels: {', '.join(channels_searched)}")
                
                if not reaction_message:
                    logger.warning(f"Could not find reaction message {message_id}")
                    # Continue without updating the reaction message
                elif not reaction_message.embeds:
                    logger.warning(f"Reaction message {message_id} has no embeds")
                else:
                    logger.info(f"Found reaction message with {len(reaction_message.embeds)} embeds")
                    embed = reaction_message.embeds[0]
                    new_embed = discord.Embed.from_dict(embed.to_dict())
                    
                    # Update description to reflect team-based nature
                    description = new_embed.description or ""
                    if "if you will play" in description:
                        description = description.replace("if you will play", f"to join the CTF! (Teams of {team_size})")
                    else:
                        description += f"\n\nClick the ✅ to join the CTF! (Teams of {team_size})"
                    new_embed.description = description
                    
                    # Update/replace the role field with team registration info
                    updated_field = False
                    for i, field in enumerate(new_embed.fields):
                        if field.name == "Role":
                            new_embed.set_field_at(
                                i,
                                name="Team Registration",
                                value=f"React with ✅ to get the {existing_role.mention} role and access to the main CTF channel. Teams of {team_size} will be created automatically and you'll get access to your team channel.",
                                inline=False
                            )
                            updated_field = True
                            logger.info("Updated existing Role field to Team Registration")
                            break
                    
                    if not updated_field:
                        new_embed.add_field(
                            name="Team Registration",
                            value=f"React with ✅ to get the {existing_role.mention} role and access to the main CTF channel. Teams of {team_size} will be created automatically and you'll get access to your team channel.",
                            inline=False
                        )
                        logger.info("Added new Team Registration field")
                    
                    await reaction_message.edit(embed=new_embed)
                    logger.info("Successfully updated reaction message embed for team-based CTF")
                    
            except Exception as e:
                logger.error(f"Error updating reaction message embed: {str(e)}", exc_info=True)
            
            # Send a summary message to the main channel where the reaction message is
            summary_embed = discord.Embed(
                title=f"🔄 {ctf_name} Converted to Team-Based Format",
                description=f"This CTF has been converted from a single large team to multiple smaller teams of {team_size} members each.",
                color=discord.Color.blue()
            )
            summary_embed.add_field(
                name="Conversion Summary",
                value=f"**Members converted:** {len(members_with_role)}\n**Teams created:** {len(created_teams)}\n**Team size:** {team_size}",
                inline=False
            )
            summary_embed.add_field(
                name="Team Assignments",
                value="\n".join(team_assignments),
                inline=False
            )
            summary_embed.add_field(
                name="What's Next?",
                value="• Check your team channels for your teammates\n• New registrations will automatically create balanced teams\n• Team channels are private to team members only",
                inline=False
            )
            
            # Send to the main channel where the reaction message is
            await ctf_main_channel.send(embed=summary_embed)
            
            # Also send a notification to the current channel if it's different
            if target_channel != ctf_main_channel:
                current_channel_embed = discord.Embed(
                    title=f"🔄 {ctf_name} Converted to Teams",
                    description=f"This CTF has been converted to team-based format with teams of {team_size} members. Check {ctf_main_channel.mention} for full details.",
                    color=discord.Color.blue()
                )
                await target_channel.send(embed=current_channel_embed)
            
            # Send success message to command user
            success_msg = f"✅ **CTF conversion completed!**\n\n"
            success_msg += f"**CTF:** {ctf_name}\n"
            success_msg += f"**Reaction message found in:** {ctf_main_channel.mention}\n"
            success_msg += f"**Members converted:** {len(members_with_role)}\n"
            success_msg += f"**Teams created:** {len(created_teams)}\n"
            success_msg += f"**Team size:** {team_size}\n\n"
            success_msg += f"**Teams created:** {', '.join(map(str, created_teams))}\n"
            success_msg += f"**Event role (main channel access):** {existing_role.name}"
            
            await interaction.followup.send(success_msg)
            logger.info(f"Successfully converted CTF {ctf_name} to team-based format by {interaction.user.name}#{interaction.user.discriminator}")
            
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in converttoteams command:\n{error_traceback}")
            await interaction.followup.send(f"Error converting CTF to teams: {str(e)}", ephemeral=True)