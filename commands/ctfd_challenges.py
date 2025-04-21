import discord
from discord.ext import commands
import aiohttp
import asyncio
import traceback
import re
from bs4 import BeautifulSoup
import logging

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

async def login_to_ctfd(session, url, username, password):
    """
    Log in to a CTFd instance and return the authenticated session
    """
    login_url = f"{url.rstrip('/')}/login"
    
    # First get the login page to extract the CSRF token
    async with session.get(login_url) as response:
        if response.status != 200:
            raise Exception(f"Failed to access login page: HTTP {response.status}")
        
        text = await response.text()
        soup = BeautifulSoup(text, 'html.parser')
        
        # Extract the CSRF token
        csrf_token = soup.find('input', {'name': 'nonce'})
        if not csrf_token:
            raise Exception("Could not find CSRF token on login page")
        
        csrf_token = csrf_token.get('value', '')
    
    # Now attempt to login
    login_data = {
        'name': username,
        'password': password,
        'nonce': csrf_token
    }
    
    async with session.post(login_url, data=login_data, allow_redirects=True) as response:
        if response.status != 200:
            raise Exception(f"Login failed: HTTP {response.status}")
        
        # Check if login was successful
        text = await response.text()
        if "Your username or password is incorrect" in text:
            raise Exception("Invalid username or password")
            
        return session

async def get_ctfd_challenges(session, url):
    """
    Get all challenges from a CTFd instance
    """
    challenges_url = f"{url.rstrip('/')}/api/v1/challenges"
    
    async with session.get(challenges_url) as response:
        if response.status != 200:
            raise Exception(f"Failed to fetch challenges: HTTP {response.status}")
        
        data = await response.json()
        
        if not data.get('success'):
            raise Exception("API returned error when fetching challenges")
            
        return data.get('data', [])

async def get_challenge_details(session, url, challenge_id):
    """
    Get details for a specific challenge
    """
    challenge_url = f"{url.rstrip('/')}/api/v1/challenges/{challenge_id}"
    
    async with session.get(challenge_url) as response:
        if response.status != 200:
            raise Exception(f"Failed to fetch challenge details: HTTP {response.status}")
        
        data = await response.json()
        
        if not data.get('success'):
            raise Exception("API returned error when fetching challenge details")
            
        return data.get('data', {})

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

def truncate_text(text, max_length=1024):
    """
    Truncate text to max_length and add ellipsis if needed
    """
    if not text:
        return "None"
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length-3] + "..."

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
        name="ctf_ctfd",
        description="Fetch challenges from a CTFd instance and create threads for each",
        guild=discord.Object(id=guild_id)
    )
    async def ctfd_challenges(
        interaction: discord.Interaction,
        url: str,
        username: str,
        password: str,
        category: str = None,
        only_new: bool = True
    ):
        required_permissions = [
            'view_channel', 'send_messages', 'create_public_threads', 
            'send_messages_in_threads', 'embed_links', 'manage_messages'
        ]
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for ctfdchalls command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'ctfdchalls' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        
        # Only allow this command to be used in CTF channels
        channel = interaction.channel
        if not channel.category or not channel.category.name.endswith("CTFs"):
            await interaction.response.send_message(
                "This command can only be used in channels within a CTF category!",
                ephemeral=True
            )
            return
        
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Get existing challenges if we're only adding new ones
            existing_challenges = set()
            if only_new:
                existing_challenges = await get_existing_challenges(channel)
                logger.info(f"Found {len(existing_challenges)} existing challenge threads")
            
            # Normalize the URL
            if not url.startswith(('http://', 'https://')):
                url = f"https://{url}"
            url = url.rstrip('/')
            
            # Create a session and login
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as session:
                try:
                    await login_to_ctfd(session, url, username, password)
                    logger.info(f"Successfully logged in to {url} as {username}")
                    
                    # Get challenges
                    challenges = await get_ctfd_challenges(session, url)
                    
                    if not challenges:
                        await interaction.followup.send("No challenges found. Make sure the competition has started.")
                        return
                    
                    # Filter by category if provided
                    if category:
                        challenges = [c for c in challenges if c.get('category', '').lower() == category.lower()]
                        if not challenges:
                            await interaction.followup.send(f"No challenges found in category '{category}'.")
                            return
                    
                    # Identify new challenges
                    new_challenges = []
                    for challenge in challenges:
                        challenge_name = challenge.get('name', '')
                        normalized_name = re.sub(r'[^\w\s]', '', challenge_name).lower()
                        normalized_name = re.sub(r'\s+', ' ', normalized_name).strip()
                        
                        if not only_new or normalized_name not in existing_challenges:
                            new_challenges.append(challenge)
                        else:
                            logger.info(f"Skipping existing challenge: {challenge_name}")
                    
                    if not new_challenges:
                        await interaction.followup.send("No new challenges found. All challenges already have threads.")
                        return
                    
                    # Group challenges by category for reporting
                    challenges_by_category = {}
                    for challenge in new_challenges:
                        cat = challenge.get('category', 'Uncategorized')
                        if cat not in challenges_by_category:
                            challenges_by_category[cat] = []
                        challenges_by_category[cat].append(challenge)
                    
                    # Send a summary message to the channel
                    summary_message = []
                    for cat_name, cat_challenges in challenges_by_category.items():
                        summary_message.append(f"**{cat_name}**: {len(cat_challenges)} new challenges")
                    
                    if only_new:
                        title = f"Fetched new challenges from {url}"
                    else:
                        title = f"Fetched all challenges from {url}"
                        
                    summary_embed = discord.Embed(
                        title=title,
                        description="\n".join(summary_message),
                        color=discord.Color.blue()
                    )
                    await channel.send(embed=summary_embed)
                    
                    # Count created threads
                    thread_count = 0
                    failed_count = 0
                    
                    # Create threads for each new challenge
                    for challenge in new_challenges:
                        try:
                            # Get more details about the challenge
                            challenge_details = await get_challenge_details(session, url, challenge['id'])
                            
                            # Get the category for the thread name prefix
                            category_name = challenge.get('category', 'Uncategorized')
                            
                            # Create a thread for the challenge
                            challenge_name = challenge.get('name', f"Challenge {challenge['id']}")
                            safe_name = re.sub(r'[^\w\s-]', '', challenge_name).strip()
                            thread_name = f"[{category_name}] {safe_name}"
                            
                            # Ensure the thread name is within Discord's length limit
                            if len(thread_name) > 100:
                                thread_name = thread_name[:97] + "..."
                            
                            thread = await channel.create_thread(
                                name=thread_name,
                                type=discord.ChannelType.public_thread,
                                auto_archive_duration=10080  # 7 days
                            )
                            
                            # Truncate description if needed (4096 character limit for embed descriptions)
                            description = truncate_text(challenge_details.get('description', 'No description available'), 4000)
                            
                            # Create embed for the challenge details
                            challenge_embed = discord.Embed(
                                title=challenge.get('name', 'Unnamed Challenge'),
                                description=description,
                                color=discord.Color.green(),
                                url=f"{url}/challenges#{challenge['id']}"
                            )
                            
                            challenge_embed.add_field(
                                name="Category", 
                                value=category_name,
                                inline=True
                            )
                            
                            challenge_embed.add_field(
                                name="Points", 
                                value=str(challenge.get('value', 'Unknown')),
                                inline=True
                            )
                            
                            challenge_embed.add_field(
                                name="Solves", 
                                value=str(challenge.get('solves', 'Unknown')),
                                inline=True
                            )
                            
                            # Add any files as fields
                            if 'files' in challenge_details and challenge_details['files']:
                                file_links = []
                                for file in challenge_details['files']:
                                    file_url = file if file.startswith(('http://', 'https://')) else f"{url}{file}"
                                    file_name = file_url.split('/')[-1]
                                    file_links.append(f"[{file_name}]({file_url})")
                                
                                # Join file links but truncate if too long
                                file_links_text = "\n".join(file_links) if file_links else "None"
                                file_links_text = truncate_text(file_links_text, 1024)
                                
                                challenge_embed.add_field(
                                    name="Files",
                                    value=file_links_text,
                                    inline=False
                                )
                            
                            # Send the challenge details in the thread
                            await thread.send(embed=challenge_embed)
                            thread_count += 1
                            
                            # Avoid rate limiting
                            await asyncio.sleep(1)
                            
                        except Exception as e:
                            logger.error(f"Error creating thread for challenge {challenge.get('name', challenge['id'])}: {str(e)}")
                            failed_count += 1
                            continue
                    
                    # Clean up the "Bot started a thread" messages
                    success = await cleanup_thread_messages(channel, interaction.client.user.id)
                    cleanup_status = ""
                    if not success:
                        cleanup_status = "\nCould not clean up the thread notification messages. Make sure the bot has 'Manage Messages' permission."
                    
                    # Create a well-formatted summary embed for the public channel
                    result_embed = discord.Embed(
                        title="Challenge Import Complete",
                        color=discord.Color.green() if thread_count > 0 else discord.Color.orange()
                    )
                    
                    # Add basic stats
                    result_embed.add_field(
                        name="Summary",
                        value=f"✅ **{thread_count}** new challenge threads created\n" + 
                              (f"⚠️ **{failed_count}** challenges failed\n" if failed_count > 0 else "") +
                              (f"⏭️ **{len(existing_challenges)}** existing challenges skipped" if only_new and len(existing_challenges) > 0 else ""),
                        inline=False
                    )
                    
                    # Add source information
                    result_embed.add_field(
                        name="Source",
                        value=f"{url}",
                        inline=True
                    )
                    
                    # Add cleanup status if applicable
                    if not success:
                        result_embed.add_field(
                            name="⚠️ Notice",
                            value="Could not clean up thread notification messages. Make sure the bot has 'Manage Messages' permission.",
                            inline=False
                        )
                    
                    # Set footer with timestamp
                    result_embed.set_footer(text=f"Imported by {interaction.user.display_name}")
                    result_embed.timestamp = discord.utils.utcnow()
                    
                    # Send the results embed to the channel
                    await channel.send(embed=result_embed)
                    
                    # Create a simple message for the ephemeral response
                    simple_message = f"Successfully created {thread_count} new challenge threads!"
                    if failed_count > 0:
                        simple_message += f" ({failed_count} challenges failed to create properly)"
                    if only_new and len(existing_challenges) > 0:
                        simple_message += f" Skipped {len(existing_challenges)} existing challenges."
                    
                    await interaction.followup.send(
                        simple_message,
                        ephemeral=True
                    )
                    
                except Exception as e:
                    logger.error(f"Error authenticating to CTFd: {str(e)}")
                    await interaction.followup.send(
                        f"Error: {str(e)}",
                        ephemeral=True
                    )
                    
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in ctfdchalls command:\n{error_traceback}")
            await interaction.followup.send(
                f"An error occurred: {str(e)}",
                ephemeral=True
            )