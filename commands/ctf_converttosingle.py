import discord
from discord.ext import commands
import logging
import traceback
import re
from typing import Optional
from db import (save_reaction_role, get_team_info, save_team_info, get_team_members, 
                remove_team_member, cleanup_ctf_data, get_ctf_by_channel,
                get_reaction_message_channel)

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_converttosingle",
        description="Convert a team-based CTF back to a single traditional CTF with one role",
        guild=discord.Object(id=guild_id)
    )
    async def convert_to_single(
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None
    ):
        """
        Convert a team-based CTF back to a traditional single-role CTF
        
        Parameters:
        -----------
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
            logger.error(f"Missing permissions for converttosingle command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'converttosingle' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        logger.info(f"Convert to Single Parameters: channel={channel.name if channel else 'current'}")
        
        try:
            # Check if user has permission to manage roles
            if not interaction.user.guild_permissions.manage_roles:
                await interaction.response.send_message("You don't have permission to convert CTF teams!", ephemeral=True)
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
            
            # Check if it's a team-based CTF
            if message_id not in bot.reaction_roles:
                await interaction.followup.send("CTF configuration not found in bot memory. Try restarting the bot.", ephemeral=True)
                return
            
            role_data = bot.reaction_roles[message_id]
            logger.info(f"Role data for message {message_id}: {role_data}")
            
            if 'team_config' not in role_data:
                await interaction.followup.send("This CTF is not team-based! It's already a traditional single-role CTF.", ephemeral=True)
                return
            
            team_config = role_data['team_config']
            
            # Get the event role (this will become the single role)
            event_role_id = team_config.get('event_role_id') or role_data.get('role_id')
            if not event_role_id:
                await interaction.followup.send("No event role found for this CTF! Cannot convert.", ephemeral=True)
                return
            
            event_role = interaction.guild.get_role(event_role_id)
            if not event_role:
                await interaction.followup.send("Event role not found! The role may have been deleted.", ephemeral=True)
                return
            
            logger.info(f"Converting team-based CTF: {team_config['ctf_name']} with event role: {event_role.name}")
            
            # Get all team members and their teams
            all_teams = get_team_members(message_id)
            
            if not all_teams:
                logger.info("No teams found, just converting configuration")
            else:
                logger.info(f"Found {len(all_teams)} teams to clean up: {list(all_teams.keys())}")
            
            guild = interaction.guild
            category = guild.get_channel(team_config['category_id'])
            
            # Collect all team members for summary
            total_members = 0
            teams_deleted = []
            
            # Clean up all team roles and channels
            for team_num, members in all_teams.items():
                logger.info(f"Cleaning up team {team_num} with {len(members)} members")
                
                total_members += len(members)
                teams_deleted.append(team_num)
                
                # Remove team role from all members (they keep the event role)
                team_role_name = f"{team_config['ctf_name'].lower()}-team-{team_num}"
                team_role = discord.utils.get(guild.roles, name=team_role_name)
                
                if team_role:
                    for member_id in members:
                        member = guild.get_member(member_id)
                        if member:
                            try:
                                await member.remove_roles(team_role)
                                logger.debug(f"Removed team role from user {member_id}")
                                # Remove from database
                                remove_team_member(message_id, member_id)
                            except Exception as e:
                                logger.error(f"Error removing team role from user {member_id}: {str(e)}")
                    
                    # Delete the team role
                    try:
                        await team_role.delete(reason="CTF converted to single-role format")
                        logger.info(f"Deleted team role: {team_role_name}")
                    except Exception as e:
                        logger.error(f"Error deleting team role {team_role_name}: {str(e)}")
                else:
                    logger.warning(f"Team role {team_role_name} not found")
                
                # Delete the team channel
                team_channel_name = f"{team_config['ctf_name'].lower().replace(' ', '-')}-team-{team_num}"
                team_channel_name = re.sub(r'[^a-zA-Z0-9_-]', '', team_channel_name)
                team_channel = discord.utils.get(category.channels, name=team_channel_name)
                
                if team_channel:
                    try:
                        await team_channel.delete(reason="CTF converted to single-role format")
                        logger.info(f"Deleted team channel: {team_channel_name}")
                    except Exception as e:
                        logger.error(f"Error deleting team channel {team_channel_name}: {str(e)}")
                else:
                    logger.warning(f"Team channel {team_channel_name} not found")
            
            # Update the main channel permissions (event role gets full access)
            try:
                await target_channel.edit(overwrites={
                    guild.default_role: discord.PermissionOverwrite(
                        read_messages=False,
                        send_messages=False
                    ),
                    event_role: discord.PermissionOverwrite(
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
                logger.info("Updated main channel permissions for traditional CTF")
            except Exception as e:
                logger.error(f"Error updating main channel permissions: {str(e)}")
            
            # Update the reaction role configuration in database and memory
            save_reaction_role(message_id, event_role.id, '✅', target_channel.id, role_data.get('reaction_message_channel_id'))
            
            # Remove team configuration from database
            try:
                # Remove team config and team member records
                conn = __import__('sqlite3').connect('ctf_bot.db')
                c = conn.cursor()
                c.execute('DELETE FROM team_configs WHERE message_id = ?', (message_id,))
                c.execute('DELETE FROM team_members WHERE message_id = ?', (message_id,))
                conn.commit()
                conn.close()
                logger.info("Cleaned up team configuration from database")
            except Exception as e:
                logger.error(f"Error cleaning up team configuration: {str(e)}")
            
            # Update bot memory to traditional CTF
            bot.reaction_roles[message_id] = {
                'role_id': event_role.id,
                'emoji': '✅',
                'channel_id': target_channel.id,
                'reaction_message_channel_id': role_data.get('reaction_message_channel_id')
            }
            
            logger.info("Updated reaction role configuration to traditional CTF")
            
            # Update the reaction message embed to reflect traditional nature
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
                            save_reaction_role(message_id, event_role.id, '✅', target_channel.id, channel_to_search.id)
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
                    
                    # Update description to reflect traditional nature
                    description = new_embed.description or ""
                    # Remove team-specific language
                    if "Teams of" in description:
                        # Remove the team size info
                        description = re.sub(r'\(Teams of \d+\)', '', description)
                    if "to join the CTF!" in description:
                        description = description.replace("to join the CTF!", "if you will play")
                    new_embed.description = description.strip()
                    
                    # Update/replace team registration field with traditional role field
                    updated_field = False
                    for i, field in enumerate(new_embed.fields):
                        if field.name == "Team Registration":
                            new_embed.set_field_at(
                                i,
                                name="Role",
                                value=f"React with ✅ to get the {event_role.mention} role and access to the CTF channel",
                                inline=False
                            )
                            updated_field = True
                            logger.info("Updated Team Registration field to Role")
                            break
                    
                    if not updated_field:
                        # Look for any field that mentions teams and update it
                        for i, field in enumerate(new_embed.fields):
                            if "team" in field.name.lower() or "team" in field.value.lower():
                                new_embed.set_field_at(
                                    i,
                                    name="Role",
                                    value=f"React with ✅ to get the {event_role.mention} role and access to the CTF channel",
                                    inline=False
                                )
                                updated_field = True
                                logger.info("Updated team-related field to Role")
                                break
                    
                    await reaction_message.edit(embed=new_embed)
                    logger.info("Successfully updated reaction message embed for traditional CTF")
                        
            except Exception as e:
                logger.error(f"Error updating reaction message embed: {str(e)}", exc_info=True)
            
            # Send a summary message to the main channel
            summary_embed = discord.Embed(
                title=f"🔄 {team_config['ctf_name']} Converted to Traditional Format",
                description=f"This CTF has been converted from team-based format back to a single traditional CTF.",
                color=discord.Color.green()
            )
            summary_embed.add_field(
                name="Conversion Summary",
                value=f"**Members affected:** {total_members}\n**Teams removed:** {len(teams_deleted)}\n**Single role:** {event_role.mention}",
                inline=False
            )
            if teams_deleted:
                summary_embed.add_field(
                    name="Teams Removed",
                    value=f"Teams {', '.join(map(str, teams_deleted))} and their channels have been deleted",
                    inline=False
                )
            summary_embed.add_field(
                name="What Changed?",
                value=f"• All team roles and channels removed\n• Everyone now uses the single {event_role.mention} role\n• Full access to the main CTF channel\n• New reactions will give the single role",
                inline=False
            )
            
            await target_channel.send(embed=summary_embed)
            
            # Send success message to command user
            success_msg = f"✅ **CTF conversion completed!**\n\n"
            success_msg += f"**CTF:** {team_config['ctf_name']}\n"
            success_msg += f"**Members affected:** {total_members}\n"
            success_msg += f"**Teams removed:** {len(teams_deleted)}\n"
            success_msg += f"**Single role:** {event_role.mention}\n\n"
            if teams_deleted:
                success_msg += f"**Teams deleted:** {', '.join(map(str, teams_deleted))}\n"
            success_msg += f"**CTF is now traditional** - everyone uses one role and one channel!"
            
            await interaction.followup.send(success_msg)
            logger.info(f"Successfully converted CTF {team_config['ctf_name']} to traditional format by {interaction.user.name}#{interaction.user.discriminator}")
            
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in converttosingle command:\n{error_traceback}")
            await interaction.followup.send(f"Error converting CTF to single format: {str(e)}", ephemeral=True)