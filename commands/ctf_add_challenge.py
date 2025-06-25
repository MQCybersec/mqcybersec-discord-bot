import discord
from discord.ext import commands
import logging
import traceback
import re
import asyncio

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def truncate_text(text, max_length=1024):
    """
    Truncate text to max_length and add ellipsis if needed
    """
    if not text:
        return "None"
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length-3] + "..."

async def cleanup_thread_messages(channel, bot_id):
    """
    Clean up the 'Bot started a thread' messages
    """
    try:
        # Get recent messages and find the thread starter messages
        async for message in channel.history(limit=100):
            # Check if it's a system message about thread creation
            if message.type == discord.MessageType.thread_created:
                try:
                    # Delete the message
                    await message.delete()
                    await asyncio.sleep(0.5)  # Small delay to prevent rate limiting
                except discord.Forbidden:
                    logger.warning("Bot does not have permission to delete messages")
                    return False
                except Exception as e:
                    logger.warning(f"Error deleting message: {str(e)}")
                    continue
        
        return True
    except Exception as e:
        logger.error(f"Error in cleanup_thread_messages: {str(e)}")
        return False

async def get_existing_challenges(channel):
    """
    Get a set of existing challenge names from the channel's threads
    with improved detection for special characters
    """
    existing_challenges = set()
    processed_threads = []
    
    # Helper function to normalize challenge names for comparison
    def normalize_name(name):
        # Remove special characters, convert to lowercase
        normalized = re.sub(r'[^\w\s]', '', name).lower()
        # Remove extra spaces
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
    # Collect all active threads
    for thread in channel.threads:
        thread_name = thread.name
        processed_threads.append(thread_name)
        
        # Extract challenge name from thread name - typically in format "[Category] Challenge Name"
        if "]" in thread_name:
            # Extract just the challenge name part
            challenge_name = thread_name.split("]", 1)[1].strip()
            existing_challenges.add(normalize_name(challenge_name))
        else:
            # If no category prefix, just use the whole name
            existing_challenges.add(normalize_name(thread_name))
    
    # Also check archived threads
    async for thread in channel.archived_threads():
        thread_name = thread.name
        processed_threads.append(thread_name)
        
        if "]" in thread_name:
            challenge_name = thread_name.split("]", 1)[1].strip()
            existing_challenges.add(normalize_name(challenge_name))
        else:
            existing_challenges.add(normalize_name(thread_name))
    
    # Log for debugging
    logger.info(f"Found threads: {', '.join(processed_threads)}")
    logger.info(f"Normalized challenge names: {', '.join(existing_challenges)}")
    
    return existing_challenges

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_add_challenge",
        description="Add a single challenge with custom details and create a thread for it",
        guild=discord.Object(id=guild_id)
    )
    async def add_challenge(
        interaction: discord.Interaction,
        name: str,
        category: str,
        description: str = None,
        points: int = 0,
        url: str = None
    ):
        required_permissions = [
            'view_channel', 'send_messages', 'create_public_threads', 
            'send_messages_in_threads', 'embed_links', 'manage_messages'
        ]
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for add_challenge command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'ctf_add_challenge' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        
        # Only allow this command to be used in CTF channels
        channel = interaction.channel
        
        # Check if the channel is in a category
        if not channel.category:
            await interaction.response.send_message(
                "This command can only be used in channels within a CTF category!",
                ephemeral=True
            )
            return
            
        # Check if the category name follows the pattern "YYYY CTFs" (e.g., "2025 CTFs")
        category_name = channel.category.name
        if not re.match(r'^\d{4}\s+CTFs$', category_name):
            await interaction.response.send_message(
                f"This command can only be used in channels within a CTF category (e.g., '2025 CTFs')!",
                ephemeral=True
            )
            return
        
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Get existing challenges to check for duplicates
            existing_challenges = await get_existing_challenges(channel)
            
            # Check if challenge already exists
            normalized_name = re.sub(r'[^\w\s]', '', name).lower()
            normalized_name = re.sub(r'\s+', ' ', normalized_name).strip()
            
            if normalized_name in existing_challenges:
                await interaction.followup.send(
                    f"A challenge with the name '{name}' already exists. Please use a different name.",
                    ephemeral=True
                )
                return
            
            # Format the thread name
            safe_name = re.sub(r'[^\w\s-]', '', name).strip()
            thread_name = f"[{category}] {safe_name}"
            
            # Ensure the thread name is within Discord's length limit
            if len(thread_name) > 100:
                thread_name = thread_name[:97] + "..."
            
            # Create a thread for the challenge
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.public_thread,
                auto_archive_duration=10080  # 7 days
            )
            
            # Prepare description
            if not description:
                description = "No description provided."
            else:
                description = truncate_text(description, 4000)
            
            # Create embed for the challenge details
            challenge_embed = discord.Embed(
                title=name,
                description=description,
                color=discord.Color.green(),
                url=url if url else None
            )
            
            challenge_embed.add_field(
                name="Category", 
                value=category,
                inline=True
            )
            
            if points > 0:
                challenge_embed.add_field(
                    name="Points", 
                    value=str(points),
                    inline=True
                )
            
            # Add creator info
            challenge_embed.set_footer(text=f"Added by {interaction.user.display_name}")
            
            # Send the challenge details in the thread
            await thread.send(embed=challenge_embed)
            
            # Clean up the "Bot started a thread" messages
            success = await cleanup_thread_messages(channel, interaction.client.user.id)
            cleanup_status = ""
            if not success:
                cleanup_status = "\nCould not clean up the thread notification messages. Make sure the bot has 'Manage Messages' permission."
            
            # Notify in the main channel
            notification_embed = discord.Embed(
                title=f"New Challenge Added: {name}",
                description=f"Category: **{category}**" + (f"\nPoints: **{points}**" if points > 0 else ""),
                color=discord.Color.blue()
            )
            notification_embed.set_footer(text=f"Added by {interaction.user.display_name}")
            
            await channel.send(embed=notification_embed)
            
            # Success message to the user
            await interaction.followup.send(
                f"Successfully created challenge thread for '{name}'!{cleanup_status}",
                ephemeral=True
            )
            
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in add_challenge command:\n{error_traceback}")
            await interaction.followup.send(
                f"An error occurred: {str(e)}",
                ephemeral=True
            )