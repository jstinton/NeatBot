import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { REST, Routes } from 'discord.js';
import { config, requireRuntimeConfig } from './config.js';

async function loadCommandData() {
  const commandsPath = path.join(process.cwd(), 'src', 'commands');
  const files = (await fs.readdir(commandsPath)).filter((file) => file.endsWith('.js'));
  const commands = [];

  for (const file of files) {
    const command = await import(pathToFileURL(path.join(commandsPath, file)));
    commands.push(command.data.toJSON());
  }

  return commands;
}

async function main() {
  requireRuntimeConfig();
  const commands = await loadCommandData();
  const rest = new REST({ version: '10' }).setToken(config.token);

  if (config.guildId) {
    await rest.put(
      Routes.applicationGuildCommands(config.clientId, config.guildId),
      { body: commands }
    );
    console.log(`Registered ${commands.length} guild command(s) for ${config.guildId}.`);
    return;
  }

  await rest.put(Routes.applicationCommands(config.clientId), { body: commands });
  console.log(`Registered ${commands.length} global command(s).`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
