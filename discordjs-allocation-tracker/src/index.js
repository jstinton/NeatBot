import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { Client, Collection, GatewayIntentBits, Partials } from 'discord.js';
import { requireRuntimeConfig, config } from './config.js';
import { initDb } from './database.js';

async function loadCommands(client) {
  client.commands = new Collection();
  const commandsPath = path.join(process.cwd(), 'src', 'commands');
  const files = (await fs.readdir(commandsPath)).filter((file) => file.endsWith('.js'));

  for (const file of files) {
    const command = await import(pathToFileURL(path.join(commandsPath, file)));
    client.commands.set(command.data.name, command);
  }
}

async function loadEvents(client) {
  const eventsPath = path.join(process.cwd(), 'src', 'events');
  const files = (await fs.readdir(eventsPath)).filter((file) => file.endsWith('.js'));

  for (const file of files) {
    const event = await import(pathToFileURL(path.join(eventsPath, file)));
    client.on(event.name, (...args) => event.execute(...args));
  }
}

async function main() {
  requireRuntimeConfig();
  await initDb();

  const client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.MessageContent
    ],
    partials: [Partials.Channel]
  });

  client.once('ready', () => {
    console.log(`NeatBot allocation tracker online as ${client.user.tag}`);
    console.log(`Listening in channel named: ${config.trackerChannelName}`);
  });

  await loadCommands(client);
  await loadEvents(client);

  if (process.argv.includes('--smoke')) {
    console.log(`Loaded ${client.commands.size} command(s). Smoke check passed.`);
    process.exit(0);
  }

  await client.login(config.token);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
