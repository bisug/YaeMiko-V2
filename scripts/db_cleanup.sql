-- Cleanup for the YaeMiko PostgreSQL schema.
--
-- Nothing here runs by itself: the bot never executes this file. It is for an
-- operator to read and run by hand.
--
-- The bot creates its tables with create_all, which never drops a table it did
-- not create. Two kinds of leftovers therefore pile up in a database that was
-- used before:
--
--   1. tables from the MongoDB era, with no model behind them any more
--   2. columns a model no longer declares
--
-- The column shapes and the indexes the models need are handled by the bot
-- itself: the modules that own a table run a migration at start up, and
-- create_pending_indexes() builds the indexes once the tables exist. Run the
-- bot once after an upgrade and both are in place.

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- 1. Report: tables with no model behind them
--
-- The list mixes the bot's own leftovers with tables that belong to another
-- application sharing this database. The second group is why this file only
-- reports first: dropping a table another app owns breaks that app, not this
-- one.
-- ---------------------------------------------------------------------------

select table_name,
       (xpath('/row/c/text()', query_to_xml(format(
           'select count(*) as c from %I.%I', table_schema, table_name),
           false, true, '')))[1]::text::bigint as rows
from information_schema.tables
where table_schema = 'public'
  and table_type = 'BASE TABLE'
  and table_name not in (
      -- The tables the bot's models own. Keep in step with
      -- Database/sql/*.py when a module gains or loses a table.
      'access_connection', 'action_topics', 'afk_user', 'allowed_items',
      'anime_group_settings', 'anime_tokens', 'antiflood', 'antiflood_settings',
      'approval', 'bans_feds', 'blacklist', 'blacklist_settings',
      'blacklist_stickers', 'blsticker_settings', 'bot_to_bot',
      'captcha_settings', 'captcha_solved', 'chat_feds', 'chat_locale',
      'chat_members', 'chat_toggles', 'chats', 'clean_service',
      'cleaner_bluetext_chat_ignore_commands', 'cleaner_bluetext_chat_setting',
      'cleaner_bluetext_global_ignore_commands', 'connection',
      'connection_history', 'couple', 'cust_filter_urls', 'cust_filters',
      'disabled_commands', 'feds', 'feds_settings', 'feds_subs', 'fsub_settings',
      'gban_settings', 'gbans', 'human_checks', 'karma', 'leave_urls',
      'log_channel_setting', 'log_channels', 'note_urls', 'notes', 'permissions',
      'raid_chats', 'raid_mode', 'reminds', 'restrictions', 'rules',
      'sangmata_users', 'users', 'warn_filters', 'warn_settings', 'warns',
      'welcome_mutes', 'welcome_pref', 'welcome_urls', 'whispers'
  )
order by table_name;

-- ---------------------------------------------------------------------------
-- 2. Drop the bot's own leftovers
--
-- These are the MongoDB era tables. Every one of them is empty, and no module
-- or plugin reads or writes any of them any more.
--
-- Read the report above first: if another application owns one of these
-- names, leave that table alone.
-- ---------------------------------------------------------------------------

drop table if exists anti_channel_settings;
drop table if exists anti_linked_channel_settings;
drop table if exists anti_pin_channel_settings;
drop table if exists blacklistusers;
drop table if exists chat_report_settings;
drop table if exists cust_filters_new;
drop table if exists forceSubscribe;
drop table if exists kuki_chats;
drop table if exists nightmode;
drop table if exists user_report_settings;
drop table if exists userbio;
drop table if exists userinfo;
drop table if exists wordlist;

-- ---------------------------------------------------------------------------
-- 3. Drop the columns the models no longer declare
--
-- Nothing wrote them and nothing read them, so the data in them is noise.
--
--   notes.is_reply        nothing set it, so the branch that read it never ran
--   notes.has_buttons     read by nobody
--   antiflood.user_id     only ever set to None
--   antiflood.count       the counter lives in the CHAT_FLOOD cache
--   raid_chats.notified   written by a helper nobody called
--
-- cust_filters.has_markdown is dropped by the bot itself, because the column
-- was NOT NULL and the model no longer declares it.
-- ---------------------------------------------------------------------------

alter table notes drop column if exists is_reply;
alter table notes drop column if exists has_buttons;
alter table antiflood drop column if exists user_id;
alter table antiflood drop column if exists count;
alter table raid_chats drop column if exists notified;

-- ---------------------------------------------------------------------------
-- 4. The user id columns the models declare as BIGINT
--
-- The bot widens these itself at start up, through the migrations in the
-- modules that own the table. They are written out here so the change can
-- be applied and checked on its own. A row that holds something that is
-- not a number stops the bot from widening the column, so check that
-- first.
-- ---------------------------------------------------------------------------

-- couple.c1_id and couple.c2_id were created as integer, which caps a
-- Telegram user id at 2**31-1.
alter table couple alter column c1_id type bigint using c1_id::bigint;
alter table couple alter column c2_id type bigint using c2_id::bigint;

-- feds.owner_id and bans_feds.user_id were text, while every other user
-- key in the package is a BIGINT.
alter table feds alter column owner_id type bigint using owner_id::bigint;
alter table bans_feds alter column user_id type bigint using user_id::bigint;

-- ---------------------------------------------------------------------------
-- 5. Check
-- ---------------------------------------------------------------------------

-- Every table the bot owns must be there. The row count must match the
-- number of tables the models declare.
select count(*) as bot_tables
from information_schema.tables
where table_schema = 'public'
  and table_name in (
      'access_connection', 'action_topics', 'afk_user', 'allowed_items',
      'anime_group_settings', 'anime_tokens', 'antiflood', 'antiflood_settings',
      'approval', 'bans_feds', 'blacklist', 'blacklist_settings',
      'blacklist_stickers', 'blsticker_settings', 'bot_to_bot',
      'captcha_settings', 'captcha_solved', 'chat_feds', 'chat_locale',
      'chat_members', 'chat_toggles', 'chats', 'clean_service',
      'cleaner_bluetext_chat_ignore_commands', 'cleaner_bluetext_chat_setting',
      'cleaner_bluetext_global_ignore_commands', 'connection',
      'connection_history', 'couple', 'cust_filter_urls', 'cust_filters',
      'disabled_commands', 'feds', 'feds_settings', 'feds_subs', 'fsub_settings',
      'gban_settings', 'gbans', 'human_checks', 'karma', 'leave_urls',
      'log_channel_setting', 'log_channels', 'note_urls', 'notes', 'permissions',
      'raid_chats', 'raid_mode', 'reminds', 'restrictions', 'rules',
      'sangmata_users', 'users', 'warn_filters', 'warn_settings', 'warns',
      'welcome_mutes', 'welcome_pref', 'welcome_urls', 'whispers'
  );

-- The indexes the queries need, and the ones that enforce uniqueness.
select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and indexname in (
      'chat_feds_fed_id_idx', 'chat_members_user_idx', 'connection_chat_id_idx',
      'connection_history_chat_id_idx', 'cust_filter_urls_uc', 'feds_name_uc',
      'feds_owner_uc', 'feds_subs_sub_idx', 'leave_urls_uc', 'note_urls_uc',
      'notes_name_lower_idx', 'users_username_lower_idx', 'warns_chat_id_idx',
      'welcome_urls_uc'
  )
order by indexname;
