export function quoteCommandArgument(argument: string) {
  if (!argument) return '""'
  if (!/[\s"'\\]/.test(argument)) return argument
  return `"${argument.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`
}

export function formatCommandForShell(command: string[]) {
  return command.map(quoteCommandArgument).join(" ")
}
