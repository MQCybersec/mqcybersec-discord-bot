import discord
from discord.ext import commands
import logging
import traceback
import re
from datetime import datetime
from typing import Optional

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_changetime",
        description="Change the start and/or end time of an existing CTF",
        guild=discord.Object(id=guild_id)
    )
    async def change_ctf_time(
        interaction: discord.Interaction,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None
    ):
        """
        Change the start and/or end time of an existing CTF
        
        Parameters:
        -----------
        start_time: New start time (format: YYYY-MM-DD HH:MM or YYYY-MM-DD)
        end_time: New end time (format: YYYY-MM-DD HH:MM or YYYY-MM-DD)
        channel: The CTF channel to update (defaults to current channel)
        """
        required_permissions = [
            'view_channel', 'send_messages', 'embed_links', 'read_message_history', 'manage_messages'
        ]
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for changetime command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'changetime' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        logger.info(f"Change Time Parameters: start_time={start_time}, end_time={end_time}, channel={channel.name if channel else 'current'}")
        
        try:
            # Check if user has permission to manage channels
            if not interaction.user.guild_permissions.manage_channels:
                await interaction.response.send_message("You don't have permission to change CTF times!", ephemeral=True)
                return
            
            # Validate that at least one time is provided
            if not start_time and not end_time:
                await interaction.response.send_message("Please provide at least one time to update (start_time or end_time)!", ephemeral=True)
                return
            
            # Parse and validate times
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
                        logger.info(f"Parsed start time: {start_dt} (timestamp: {start_timestamp})")
                    else:
                        await interaction.response.send_message("Invalid start time format! Use YYYY-MM-DD HH:MM or YYYY-MM-DD", ephemeral=True)
                        return
                except Exception as e:
                    logger.error(f"Error parsing start time '{start_time}': {str(e)}")
                    await interaction.response.send_message(f"Error parsing start time: {str(e)}", ephemeral=True)
                    return
            
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
                        logger.info(f"Parsed end time: {end_dt} (timestamp: {end_timestamp})")
                    else:
                        await interaction.response.send_message("Invalid end time format! Use YYYY-MM-DD HH:MM or YYYY-MM-DD", ephemeral=True)
                        return
                except Exception as e:
                    logger.error(f"Error parsing end time '{end_time}': {str(e)}")
                    await interaction.response.send_message(f"Error parsing end time: {str(e)}", ephemeral=True)
                    return
            
            # Validate that start is before end (if both provided)
            if start_timestamp and end_timestamp and start_timestamp >= end_timestamp:
                await interaction.response.send_message("Start time must be before end time!", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Determine which channel to use
            target_channel = channel if channel else interaction.channel
            
            # Check if the channel is a CTF channel
            if not target_channel.category or not target_channel.category.name.endswith("CTFs"):
                await interaction.followup.send("This command can only be used in a CTF channel!", ephemeral=True)
                return
            
            logger.info(f"Searching for CTF embeds in channel: {target_channel.name}")
            
            # Look for CTF embed messages in the channel
            ctf_embeds_found = []
            reaction_embed = None
            welcome_embed = None
            
            async for message in target_channel.history(limit=100):
                # Check if the message is from the bot and has an embed
                if message.author == bot.user and message.embeds and len(message.embeds) > 0:
                    embed = message.embeds[0]
                    
                    # Check if this is a reaction role message (has reactions)
                    if message.reactions:
                        for reaction in message.reactions:
                            if str(reaction.emoji) == '✅':
                                reaction_embed = message
                                logger.info(f"Found reaction role embed: {embed.title}")
                                break
                    
                    # Check if this is a welcome/info embed
                    elif embed.title and not welcome_embed:
                        welcome_embed = message
                        logger.info(f"Found welcome embed: {embed.title}")
                    
                    # Add to list of found embeds
                    if embed.title:
                        ctf_embeds_found.append(message)
            
            if not ctf_embeds_found:
                await interaction.followup.send("No CTF embeds found in this channel!", ephemeral=True)
                return
            
            logger.info(f"Found {len(ctf_embeds_found)} CTF embeds to update")
            
            updated_count = 0
            
            # Function to update embed description with new timestamps
            def update_embed_description(embed, start_ts, end_ts):
                description = embed.description or ""
                
                # Look for existing timestamp patterns and replace them
                timestamp_pattern = r'<t:\d+:[FfDdTtRr]>'
                existing_timestamps = re.findall(timestamp_pattern, description)
                
                if start_ts and end_ts:
                    # Both timestamps provided
                    new_time_text = f"running from <t:{start_ts}:F> to <t:{end_ts}:F>"
                    
                    # Replace existing time patterns
                    if "running from" in description:
                        # Replace existing "running from X to Y" pattern
                        running_pattern = r'running from <t:\d+:[FfDdTtRr]> to <t:\d+:[FfDdTtRr]>'
                        if re.search(running_pattern, description):
                            description = re.sub(running_pattern, new_time_text, description)
                        else:
                            # Look for other time patterns to replace
                            description = re.sub(timestamp_pattern, f"<t:{start_ts}:F> to <t:{end_ts}:F>", description, count=1)
                    elif existing_timestamps:
                        # Replace first timestamp pattern found
                        description = re.sub(timestamp_pattern, new_time_text, description, count=1)
                    else:
                        # No existing timestamps, add to description
                        if description:
                            description += f"\n\nRunning from <t:{start_ts}:F> to <t:{end_ts}:F>"
                        else:
                            description = f"Running from <t:{start_ts}:F> to <t:{end_ts}:F>"
                
                elif start_ts:
                    # Only start timestamp provided
                    new_time_text = f"<t:{start_ts}:F>"
                    if "running from" in description:
                        # Replace just the start timestamp
                        running_pattern = r'running from <t:\d+:[FfDdTtRr]>'
                        description = re.sub(running_pattern, f"running from {new_time_text}", description)
                    elif existing_timestamps:
                        # Replace first timestamp
                        description = re.sub(timestamp_pattern, new_time_text, description, count=1)
                    else:
                        # Add start time info
                        if description:
                            description += f"\n\nStarts: {new_time_text}"
                        else:
                            description = f"Starts: {new_time_text}"
                
                elif end_ts:
                    # Only end timestamp provided
                    new_time_text = f"<t:{end_ts}:F>"
                    if "to <t:" in description:
                        # Replace the end timestamp
                        end_pattern = r'to <t:\d+:[FfDdTtRr]>'
                        description = re.sub(end_pattern, f"to {new_time_text}", description)
                    elif existing_timestamps and len(existing_timestamps) > 1:
                        # Replace second timestamp if it exists
                        timestamps_found = 0
                        def replace_second_timestamp(match):
                            nonlocal timestamps_found
                            timestamps_found += 1
                            if timestamps_found == 2:
                                return new_time_text
                            return match.group(0)
                        description = re.sub(timestamp_pattern, replace_second_timestamp, description)
                    else:
                        # Add end time info
                        if description:
                            description += f"\n\nEnds: {new_time_text}"
                        else:
                            description = f"Ends: {new_time_text}"
                
                return description
            
            # Update all found embeds
            for message in ctf_embeds_found:
                try:
                    embed = message.embeds[0]
                    new_embed = discord.Embed.from_dict(embed.to_dict())
                    
                    # Update description with new timestamps
                    new_description = update_embed_description(embed, start_timestamp, end_timestamp)
                    new_embed.description = new_description
                    
                    await message.edit(embed=new_embed)
                    updated_count += 1
                    logger.info(f"Updated embed in message {message.id} with new timestamps")
                    
                except Exception as e:
                    logger.error(f"Error updating embed in message {message.id}: {str(e)}")
            
            if updated_count > 0:
                # Get CTF name from the channel or embed
                ctf_name = target_channel.name
                if reaction_embed and reaction_embed.embeds:
                    ctf_name = reaction_embed.embeds[0].title or ctf_name
                elif welcome_embed and welcome_embed.embeds:
                    ctf_name = welcome_embed.embeds[0].title or ctf_name
                
                # Create confirmation message
                time_changes = []
                if start_time:
                    time_changes.append(f"start time to {start_time}")
                if end_time:
                    time_changes.append(f"end time to {end_time}")
                
                if updated_count == 1:
                    confirm_msg = f"Updated {' and '.join(time_changes)} for **{ctf_name}**"
                else:
                    confirm_msg = f"Updated {updated_count} embeds for **{ctf_name}** with new {' and '.join(time_changes)}"
                
                await interaction.followup.send(confirm_msg)
                logger.info(f"Successfully updated {updated_count} CTF embeds in {target_channel.name} with new times by {interaction.user.name}#{interaction.user.discriminator}")
            else:
                await interaction.followup.send("No embeds were updated. Please check if the channel contains valid CTF embeds.", ephemeral=True)
                
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in changetime command:\n{error_traceback}")
            await interaction.followup.send(f"Error changing CTF times: {str(e)}", ephemeral=True)