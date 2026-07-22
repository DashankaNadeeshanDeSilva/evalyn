import typer

app = typer.Typer(help="Evalyn — evaluation agent for LLM-powered products.", no_args_is_help=True)


@app.command()
def gate(target: str = typer.Option(..., "--target", help="Path to a target pack directory.")):
    """Run the deterministic probe suite against a target and diff vs baseline."""
    typer.echo(f"gate: {target}")  # replaced in Task 13


@app.command("validate-pack")
def validate_pack(pack: str = typer.Argument(..., help="Path to a target pack directory.")):
    """Task-health check: schema, solvability, category balance."""
    typer.echo(f"validate-pack: {pack}")  # replaced in Task 12/13


if __name__ == "__main__":
    app()
