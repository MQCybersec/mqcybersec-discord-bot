import discord
from discord.ext import commands
import logging
import traceback
from typing import Optional

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_changeurl",
        description="Change the URL of an existing CTF embed",
        guild=discord.Object(id=guild_id)
    )
    async def change_ctf_url(
        interaction: discord.Interaction,
        new_url: str,
        channel: Optional[discord.TextChannel] = None
    ):
        """
        Change the URL of an existing CTF embed
        
        Parameters:
        -----------
        new_url: The new URL to set for the CTF
        channel: The CTF channel to update (defaults to current channel)
        """
        required_permissions = [
            'view_channel', 'send_messages', 'embed_links', 'read_message_history', 'manage_messages'
        ]
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for changeurl command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'changeurl' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        logger.info(f"Change URL Parameters: new_url={new_url}, channel={channel.name if channel else 'current'}")
        
        try:
            # Check if user has permission to manage channels
            if not interaction.user.guild_permissions.manage_channels:
                await interaction.response.send_message("You don't have permission to change CTF URLs!", ephemeral=True)
                return
            
            # Validate URL format
            if not new_url.startswith(('http://', 'https://')):
                await interaction.response.send_message("Please provide a valid URL starting with http:// or https://", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Determine which channel to use
            target_channel = channel if channel else interaction.channel
            
            # Check if the channel is a CTF channel
            if not target_channel.category or not target_channel.category.name.endswith("CTFs"):
                await interaction.followup.send("This command can only be used in a CTF channel!", ephemeral=True)
                return
            
            logger.info(f"Searching for CTF embed in channel: {target_channel.name}")
            
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
                    
                    # Check if this is a welcome/info embed (first embed without reactions, or with title containing CTF info)
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
            
            # Update the reaction role embed first (if found)
            if reaction_embed:
                try:
                    embed = reaction_embed.embeds[0]
                    new_embed = discord.Embed.from_dict(embed.to_dict())
                    new_embed.url = new_url
                    
                    # Update CTF URL field if it exists
                    for i, field in enumerate(new_embed.fields):
                        if field.name.lower() in ['ctf_url', 'ctf url', 'url']:
                            new_embed.set_field_at(
                                i,
                                name=field.name,
                                value=new_url,
                                inline=field.inline
                            )
                            break
                    
                    await reaction_embed.edit(embed=new_embed)
                    updated_count += 1
                    logger.info(f"Updated reaction role embed with new URL: {new_url}")
                except Exception as e:
                    logger.error(f"Error updating reaction embed: {str(e)}")
            
            # Update the welcome embed (if found and different from reaction embed)
            if welcome_embed and welcome_embed != reaction_embed:
                try:
                    embed = welcome_embed.embeds[0]
                    new_embed = discord.Embed.from_dict(embed.to_dict())
                    new_embed.url = new_url
                    
                    # Update CTF URL field if it exists
                    for i, field in enumerate(new_embed.fields):
                        if field.name.lower() in ['ctf_url', 'ctf url', 'url']:
                            new_embed.set_field_at(
                                i,
                                name=field.name,
                                value=new_url,
                                inline=field.inline
                            )
                            break
                    
                    await welcome_embed.edit(embed=new_embed)
                    updated_count += 1
                    logger.info(f"Updated welcome embed with new URL: {new_url}")
                except Exception as e:
                    logger.error(f"Error updating welcome embed: {str(e)}")
            
            # Update any other CTF embeds found
            for message in ctf_embeds_found:
                if message != reaction_embed and message != welcome_embed:
                    try:
                        embed = message.embeds[0]
                        new_embed = discord.Embed.from_dict(embed.to_dict())
                        new_embed.url = new_url
                        
                        # Update CTF URL field if it exists
                        for i, field in enumerate(new_embed.fields):
                            if field.name.lower() in ['ctf_url', 'ctf url', 'url']:
                                new_embed.set_field_at(
                                    i,
                                    name=field.name,
                                    value=new_url,
                                    inline=field.inline
                                )
                                break
                        
                        await message.edit(embed=new_embed)
                        updated_count += 1
                        logger.info(f"Updated additional embed with new URL: {new_url}")
                    except Exception as e:
                        logger.error(f"Error updating additional embed: {str(e)}")
            
            if updated_count > 0:
                # Get CTF name from the channel or embed
                ctf_name = target_channel.name
                if reaction_embed and reaction_embed.embeds:
                    ctf_name = reaction_embed.embeds[0].title or ctf_name
                elif welcome_embed and welcome_embed.embeds:
                    ctf_name = welcome_embed.embeds[0].title or ctf_name
                
                # Send confirmation
                if updated_count == 1:
                    confirm_msg = f"Updated CTF URL for **{ctf_name}** to: {new_url}"
                else:
                    confirm_msg = f"Updated {updated_count} embeds for **{ctf_name}** with new URL: {new_url}"
                
                await interaction.followup.send(confirm_msg)
                logger.info(f"Successfully updated {updated_count} CTF embeds in {target_channel.name} with URL {new_url} by {interaction.user.name}#{interaction.user.discriminator}")
            else:
                await interaction.followup.send("No embeds were updated. Please check if the channel contains valid CTF embeds.", ephemeral=True)
                
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in changeurl command:\n{error_traceback}")
            await interaction.followup.send(f"Error changing CTF URL: {str(e)}", ephemeral=True)