import discord
from discord.ext import commands
import aiohttp
import asyncio
import traceback
import re
import json
import logging
from urllib.parse import urlparse, parse_qs, unquote

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

class InvalidCredentials(Exception):
    """Exception raised when credentials are invalid"""
    pass

async def get_challenges_rCTF(session, url, token):
    """
    Get challenges using the standard rCTF API flow
    """
    # Normalize URL and token
    base_url = url.rstrip('/')
    
    # Extract token from URL if it's a full URL
    if "token=" in token:
        try:
            parsed = urlparse(token)
            token_param = parse_qs(parsed.query).get('token', [None])[0]
            if token_param:
                token = unquote(token_param)
                logger.info("Extracted and decoded token from URL parameter")
        except Exception as e:
            logger.warning(f"Error parsing token URL: {str(e)}")
    
    # Step 1: Authenticate with the teamToken
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer null"
    }
    
    logger.info(f"Authenticating to rCTF API at {base_url}/api/v1/auth/login")
    
    async with session.post(
        f"{base_url}/api/v1/auth/login", 
        json={"teamToken": token}, 
        headers=headers
    ) as response:
        if response.status != 200:
            error_text = await response.text()
            logger.error(f"Authentication failed: HTTP {response.status}, {error_text}")
            if "Your token is incorrect" in error_text or "badToken" in error_text:
                raise InvalidCredentials("Invalid login credentials")
            raise Exception(f"Authentication failed: HTTP {response.status}")
        
        try:
            response_json = await response.json()
            
            if "kind" in response_json and response_json["kind"] != "goodLogin":
                error_msg = response_json.get("message", "Unknown error")
                logger.error(f"Authentication failed: {error_msg}")
                raise InvalidCredentials(f"Authentication failed: {error_msg}")
            
            bearer_token = response_json.get('data', {}).get('authToken')
            if not bearer_token:
                logger.error("No auth token in response")
                raise Exception("No auth token in response")
                
            logger.info(f"Successfully obtained bearer token: {bearer_token[:10]}...")
        except json.JSONDecodeError:
            logger.error("Invalid JSON response from authentication endpoint")
            raise Exception("Invalid JSON response from authentication endpoint")
    
    # Step 2: Get challenges using the bearer token
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.105 Safari/537.36",
        "Referer": f"{base_url}/challs",
        "Authorization": f"Bearer {bearer_token}"
    }
    
    logger.info(f"Fetching challenges from {base_url}/api/v1/challs")
    
    # Get challenge information
    async with session.get(f"{base_url}/api/v1/challs", headers=headers) as response:
        if response.status != 200:
            logger.error(f"Failed to fetch challenges: HTTP {response.status}")
            raise Exception(f"Failed to fetch challenges: HTTP {response.status}")
        
        try:
            all_challs = await response.json()
            
            if "kind" in all_challs and all_challs["kind"] != "goodChallenges":
                error_msg = all_challs.get("message", "Unknown error")
                logger.error(f"Challenge fetch failed: {error_msg}")
                raise Exception(f"Challenge fetch failed: {error_msg}")
                
            logger.info(f"Successfully fetched {len(all_challs.get('data', []))} challenges")
        except json.JSONDecodeError:
            logger.error("Invalid JSON response from challenges endpoint")
            raise Exception("Invalid JSON response from challenges endpoint")
    
    # Step 3: Get team solves
    logger.info(f"Fetching team solves from {base_url}/api/v1/users/me")
    
    async with session.get(f"{base_url}/api/v1/users/me", headers=headers) as response:
        if response.status != 200:
            logger.warning(f"Failed to fetch team solves: HTTP {response.status}")
            # Continue without solves info - it's not critical
            team_solves = {"kind": "unknown", "data": {"solves": []}}
        else:
            try:
                team_solves = await response.json()
                
                if "kind" in team_solves and team_solves["kind"] != "goodUserData":
                    logger.warning(f"Team solves fetch returned unexpected kind: {team_solves['kind']}")
                
                logger.info("Successfully fetched team solves")
            except json.JSONDecodeError:
                logger.warning("Invalid JSON response from users/me endpoint")
                # Continue without solves info
                team_solves = {"kind": "unknown", "data": {"solves": []}}
    
    # Step 4: Process the challenges
    challenges = {}
    total_points = 0
    
    if all_challs.get('kind') == "goodChallenges":
        for chall in all_challs.get('data', []):
            cat = chall.get('category', 'Uncategorized')
            challname = chall.get('name', 'Unknown')
            value = chall.get('points', 0)
            challenge_id = chall.get('id', '')
            
            total_points += value
            
            # Create the challenge entry
            chall_entry = {
                'name': challname,
                'solved': False,
                'solver': '',
                'points': value,
                'id': challenge_id,
                'description': chall.get('description', ''),
                'files': chall.get('files', []),
                'category': cat
            }
            
            # Add to the appropriate category
            if cat in challenges:
                challenges[cat].append(chall_entry)
            else:
                challenges[cat] = [chall_entry]
    else:
        raise Exception("Error fetching challenges: Unexpected response kind")
    
    # Step 5: Add team solves
    if team_solves.get('kind') == "goodUserData":
        for solve in team_solves.get('data', {}).get('solves', []):
            # Get challenge info
            cat = solve.get('category', 'Uncategorized')
            challname = solve.get('name', 'Unknown')
            
            # Change challenge solved info if solved by team
            if cat in challenges:
                for i in range(len(challenges[cat])):
                    if challname == challenges[cat][i]['name']:
                        challenges[cat][i]['solved'] = True
    
    return {
        'challenges': challenges,
        'total_points': total_points,
        'bearer_token': bearer_token
    }

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_rctf",
        description="Fetch challenges from an RCTF instance using team token",
        guild=discord.Object(id=guild_id)
    )
    async def rctf_challenges(
        interaction: discord.Interaction,
        url: str,
        token: str = None,
        category: str = None,
        only_new: bool = True
    ):
        """
        Parameters:
        - url: The URL of the RCTF instance (can include token as parameter)
        - token: Your team token or a URL containing a token parameter
        - category: Optional category to filter challenges by
        - only_new: Whether to only create threads for challenges that don't already have threads
        """
        required_permissions = [
            'view_channel', 'send_messages', 'create_public_threads', 
            'send_messages_in_threads', 'embed_links', 'manage_messages'
        ]
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'ctf_rctf' used by {interaction.user.name}#{interaction.user.discriminator}")
        
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
            
            # Process URL and token
            # If token is None but URL contains token parameter, extract it
            if token is None and "token=" in url:
                try:
                    parsed_url = urlparse(url)
                    token_param = parse_qs(parsed_url.query).get('token', [None])[0]
                    if token_param:
                        token = token_param
                        # Update URL to base URL
                        url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                        logger.info(f"Extracted token from URL and updated URL to {url}")
                except Exception as e:
                    logger.warning(f"Error extracting token from URL: {str(e)}")
            
            # Standard URL normalization
            if not url.startswith(('http://', 'https://')):
                url = f"https://{url}"
            url = url.rstrip('/')
            
            if not token:
                await interaction.followup.send(
                    "Error: No token provided. Please provide a team token.",
                    ephemeral=True
                )
                return
            
            # Create session
            async with aiohttp.ClientSession() as session:
                try:
                    # Get challenges using RCTF API
                    result = await get_challenges_rCTF(session, url, token)
                    challenges_by_category = result['challenges']
                    
                    if not challenges_by_category:
                        await interaction.followup.send(
                            "No challenges found. Make sure the competition has started.",
                            ephemeral=True
                        )
                        return
                    
                    # Filter by category if provided
                    if category:
                        if category in challenges_by_category:
                            challenges_by_category = {category: challenges_by_category[category]}
                        else:
                            await interaction.followup.send(
                                f"No challenges found in category '{category}'.",
                                ephemeral=True
                            )
                            return
                    
                    # Identify new challenges
                    new_challenges = []
                    for cat, challenges in challenges_by_category.items():
                        for challenge in challenges:
                            challenge_name = challenge['name']
                            normalized_name = re.sub(r'[^\w\s]', '', challenge_name).lower()
                            normalized_name = re.sub(r'\s+', ' ', normalized_name).strip()
                            
                            if not only_new or normalized_name not in existing_challenges:
                                new_challenges.append(challenge)
                            else:
                                logger.info(f"Skipping existing challenge: {challenge_name}")
                    
                    if not new_challenges:
                        await interaction.followup.send(
                            "No new challenges found. All challenges already have threads.",
                            ephemeral=True
                        )
                        return
                    
                    # Group challenges by category for reporting
                    new_by_category = {}
                    for challenge in new_challenges:
                        cat = challenge['category']
                        if cat not in new_by_category:
                            new_by_category[cat] = []
                        new_by_category[cat].append(challenge)
                    
                    # Send a summary message to the channel
                    summary_message = []
                    for cat_name, cat_challenges in new_by_category.items():
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
                            # Get the category for the thread name prefix
                            category_name = challenge['category']
                            
                            # Create a thread for the challenge
                            challenge_name = challenge['name']
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
                            
                            # Prepare description
                            description = challenge.get('description', 'No description available')
                            if not description:
                                description = "No description provided."
                            
                            # Truncate if needed
                            description = truncate_text(description, 4000)
                            
                            # Create embed for the challenge details
                            challenge_embed = discord.Embed(
                                title=challenge_name,
                                description=description,
                                color=discord.Color.green(),
                                url=f"{url}/challs/{challenge.get('id', '')}"
                            )
                            
                            challenge_embed.add_field(
                                name="Category", 
                                value=category_name,
                                inline=True
                            )
                            
                            challenge_embed.add_field(
                                name="Points", 
                                value=str(challenge.get('points', 'Unknown')),
                                inline=True
                            )
                            
                            # Add solved status if available
                            solved_status = "Yes" if challenge.get('solved', False) else "No"
                            challenge_embed.add_field(
                                name="Solved", 
                                value=solved_status,
                                inline=True
                            )
                            
                            # Add files if available
                            files = challenge.get('files', [])
                            if files:
                                file_links = []
                                for file in files:
                                    file_url = file.get('url', '')
                                    file_name = file.get('name', 'file')
                                    
                                    if file_url:
                                        # Make sure URLs are absolute
                                        if not file_url.startswith(('http://', 'https://')):
                                            file_url = url.rstrip('/') + '/' + file_url.lstrip('/')
                                            
                                        file_links.append(f"[{file_name}]({file_url})")
                                
                                if file_links:
                                    file_text = "\n".join(file_links)
                                    challenge_embed.add_field(
                                        name="Files",
                                        value=file_text,
                                        inline=False
                                    )
                            
                            # Send the challenge details in the thread
                            await thread.send(embed=challenge_embed)
                            thread_count += 1
                            
                            # Avoid rate limiting
                            await asyncio.sleep(1)
                            
                        except Exception as e:
                            logger.error(f"Error creating thread for challenge {challenge.get('name', '')}: {str(e)}")
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
                    
                    # Add total points if available
                    if 'total_points' in result:
                        result_embed.add_field(
                            name="Total Points",
                            value=f"{result['total_points']} points",
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
                    
                except InvalidCredentials as e:
                    logger.error(f"Invalid credentials: {str(e)}")
                    await interaction.followup.send(
                        f"Authentication failed: {str(e)}\n\nPlease check your team token and try again.",
                        ephemeral=True
                    )
                except Exception as e:
                    logger.error(f"Error: {str(e)}")
                    await interaction.followup.send(
                        f"Error: {str(e)}",
                        ephemeral=True
                    )
        
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in rctf_challenges command:\n{error_traceback}")
            await interaction.followup.send(
                f"An error occurred: {str(e)}",
                ephemeral=True
            )


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