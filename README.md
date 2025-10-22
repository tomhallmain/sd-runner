This code is primarily a sophisticated prompt engineering application that triggers ComfyUI workflows or SD Web UI functions using advanced prompt randomization, concept management, and intelligent filtering systems.

## Warnings

- This was originally developed during early 2024, so many prompts may be out of date with current versions of the respective image generation projects.
- Though any prompt applied to any model can result in undesirable images despite properly set negative prompts, prompt randomization increases the chance that undesirable images may be generated, even if only innocuous terms are included in the prompt, because the randomness allows for wider traversal of the model's latent space. For this reason it is wise to use a local prevalidation and content filtering tool. I recommend using [simple_image_compare](https://github.com/tomhallmain/simple_image_compare) which has many other features in addition to customizable prevalidations based on CLIP and H5 models.
- A default English dictionary is used for generating random words, some of which may be found objectionable. A word with a high degree of relation to strong feelings like disgust also tends to carry a lot of prompt weight, even if it is buried in a much larger prompt with no other similar words. Luckily this will often result in an "incoherent" result with earlier models, or a slightly objectionable result with later models, but there is still a chance of problematic images being generated. As a result you may choose not to use the `random_word` prompt variable, or implement a blacklist using the provided blacklist window which blocks prompts with undesirable strings or otherwise drops them from prompts. There is a default blacklist used if none is provided, which requires extra security to clear and even to reveal its concepts.
- If sharing your computer with multiple users, consider setting a password to lock the blacklist and other features.
- Continuously viewing random images may cause small lapses in sanity. Employ total randomness with caution.
- The application can be addictive due to its infinite generation capabilities and random prompt variations. Consider enabling a timed shutdown schedule to automatically stop generation at a reasonable hour and prevent excessive usage.

## Configuration Options

`total`: By default this is 1 to run a workflow only once, however with prompt randomization the same workflow can produce a different result each time. Set to -1 to run infinitely.

`gen_order`: A single run can include multiple resolutions, models, vaes, loras, IP adapters, and control nets. Modify the gen_order list to set the order in which these combinations are run.

`redo_parameters`: Redo an image using the stored workflow found in the image, but with desired different parameters.

`model_presets`: For specific models set clip_req and prompt_tags specific to prompt modes or generally.

`prompt_presets`: For specific prompt modes add a chance to prepend or append tokens to the prompt.

`default_negative_prompt`: Any of the defaults are useful, but the negative default can be especially useful as it is often less likely to change.

## Prompt Syntax

Preset variables can be defined in the config to expand into full prompt text. To access these in the prompt UI, prepend $ or surround them with curly braces, and upon running the prompt the expansion will occur in the UI, overwriting the original prompt.

`"this is my $promptvar"` -> `"this is my expanded prompt text from promptvar"`

To use a variable without expanding it in the UI prompt, prepend two dollar signs instead of one.

`"this is my $$promptvar"` -> `"this is my $$promptvar"` (UI after starting a run) -> `this is my expanded prompt text from promptvar` (final prompt)

To define a set of words to randomly choose from, surround a comma-separated list with double square brackets, and one of the options will be chosen. All options are given equal choice weight of 1 unless one of the options has an appended colon at the end specifying the desired chance for the choice. The choice set will not be overwritten in the UI prompt.

`"A [[red,blue,yellow:2]] car"` -> `"A yellow car"`

Note that choice sets can be stored in preset prompt variables to cut down on visible prompt lengths.

## Image Resolutions

Any of the following resolution options can be used: square, portrait1, portrait2, portrait3, landscape1, landscape2, landscape3. These options are valid for both SD 1.5 and SDXL models.

To randomly skip a resolution during generation, attach a "*" to the resolution tag in the resolutions box. This is one way to help inject more randomness of output.

Note the default behavior of Control Net and IP Adapater workflows is to inherit from the source image a resolution with a matching aspect ratio. The `Override resolutions` checkbox allows you to instead use the predefined resolution tags for these workflows.

## Prompt Presets

The presets window allows you to manage presets for specific prompt and prompt mode combinations. Use this window to add presets, delete presets and to apply them to the UI.

If a presets schedule is defined in the config, the checkbox Run Preset Schedule will be enabled and presets will be run at the specified schedule if this boolean is set to True.

## Preset Schedules

After having defined presets using the presets window, you can create and modify batch schedules to run presets using the preset schedules window. Giving the preset schedules a unique name is helpful for quickly switching between them.

A preset schedule should specify the number of times each preset should run, as well as the order. If the run count for a preset is set to -1, it should inherit the run count from the value set before starting the run schedule.

Note that similar to normal image generation runs, run schedules can be queued while one is already running.

## Concepts Folder

The prompts are generated using text concepts files. Each line in each file represents a concept that can be added randomly to the prompt, based on the prompter configuration.

A custom concepts folder can be defined by setting the `concepts_dir` config option. Restart the UI and select the new folder from the concepts dropdown to use this instead of the default concepts folder.

## Concept Editor Window

A UI window for managing your concept files. Search, add, edit, or delete concepts across different categories. Access it via the "Edit Concepts" button in the main interface.

## Blacklist Window

A UI window for managing terms to filter from generated prompts. Add, remove, or toggle terms, and import/export your blacklist in CSV, JSON, or TXT formats.

**Exception Patterns**: Each blacklist item can optionally include an exception pattern (regex) that will un-filter tags that would otherwise be filtered by the primary pattern. This allows for fine-grained control - for example, you can blacklist "cat" but use an exception pattern like "cathedral" to allow that specific term through.

**Enhanced Security**: The blacklist features multi-level password protection with separate permissions for revealing and editing concepts. A default encrypted blacklist is provided for first-time users, and blacklist operations require security to be configured with user confirmation to prevent accidental data loss and exposure of problematic concepts.

## Password Protection

The application includes a password protection system that can be configured to require authentication for sensitive actions. Password settings are stored securely in the encrypted application cache. Access the Password Administration window using `<Control-P>` to configure which actions require password verification.

Protected actions include:
- Access Password Administration (defaults to protected)
- NSFW/NSFL Prompt Modes (defaults to protected)
- Reveal Blacklist Items (defaults to protected)
- Edit Blacklist (defaults to protected)
- Edit Schedules
- Edit Expansions
- Edit Presets
- Edit Concepts

## Server

Set configuration options for a server port to make use of the server while the UI is running. Calls to the server made with Python's multiprocessing client will update the UI as specified, but leave anything unspecified as already set in the UI. This can be helpful to use in conjunction with other applications that involve images. For an example, see [this class](https://github.com/tomhallmain/simple_image_compare/blob/master/extensions/sd_runner_client.py).

## Notes

The stable-diffusion-webui img2img workflow is set up as the IP Adapter workflow for that software. In the ComfyUI case, the Image to Image workflow provides a dedicated image-to-image transformation with the same inverse strength behavior, while the IP Adapter workflow uses IP-Adapter models for style transfer. In all img2img cases, modifying the IP adapter strength in the UI will inversely modify the denoising strength to produce a similar effect as IP adapter strength would for that workflow. 

The following locales are supported in the UI: en (English), de (Deutsch), es (Español), fr (Français), ja (日本語), ko (한국어), pt (Português), ru (Русский), zh (中文). Theoretically the prompt outputs could be set up for any written language that has Unicode support by modifying the existing concepts files or adding a path to the config `concepts_dirs` to override concepts files.

Excepting the concepts files, application data is encrypted for security. Logs are not currently being stored and will not be until they can be encrypted.

## Keyboard Shortcuts

- `<Control-Return>`: Run workflows
- `<Shift-R>`: Run workflows (alternative)
- `<Shift-N>`: Next preset
- `<Control-P>`: Open Password Administration window
- `<Control-Q>`: Quit application
- `<Prior>`/`<Next>`: Navigate configuration history
- `<Home>`/`<End>`: Go to first/last configuration

