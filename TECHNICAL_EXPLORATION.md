# Exploração Técnica: Captura de Logs do AutoGen no Streamlit

## O Desafio
O AutoGen imprime suas mensagens de conversa diretamente no `stdout` (console), o que dificulta a exibição em tempo real em interfaces web como o Streamlit. Além disso, o processo de construção de agentes (`AgentBuilder`) gera logs importantes sobre as decisões do LLM que também precisam ser capturados.

## Abordagens Consideradas

### 1. Redirecionamento de `sys.stdout` (A Solução Escolhida)
Esta abordagem envolve substituir o `sys.stdout` padrão do Python por uma classe personalizada que intercepta todas as chamadas de `print`.
*   **Pros:** É a solução mais abrangente ("catch-all"). Captura logs do `AgentBuilder`, mensagens de erro do sistema e a conversa dos agentes sem precisar modificar o código interno do AutoGen.
*   **Cons:** Requer tratamento cuidadoso de strings (parsing) para separar mensagens de sistema de mensagens de chat. Pode ser "ruidoso" se não filtrado.
*   **Justificativa:** Escolhida pela robustez. O `AgentBuilder` e os agentes padrão do AutoGen dependem fortemente de `print`. Implementamos um parser baseada em Regex (`StreamlitRedirector`) que identifica padrões como `Sender (to Receiver):` para formatar a saída como balões de chat nativos do Streamlit (`st.chat_message`).

### 2. AutoGen Callbacks (`register_reply`)
O AutoGen permite registrar funções de callback para processar mensagens.
*   **Pros:** Mais limpo e estruturado (recebe objetos de mensagem, não strings brutas).
*   **Cons:** Difícil de injetar dinamicamente em agentes criados pelo `AgentBuilder` sem complexidade excessiva. Não captura os logs de *construção* (o "pensamento" do arquiteto ao criar a equipe).

### 3. Handlers de Logging do Python
Configurar um `logging.Handler` personalizado.
*   **Pros:** Thread-safe e padrão da indústria.
*   **Cons:** O AutoGen usa `print` para o fluxo principal da conversa, não apenas `logging`. Capturaria apenas avisos e erros, perdendo o chat.

## Expansão Futura (Arquitetura)
Para escalar esta solução em produção:
1.  **Backend Assíncrono:** Mover a execução do AutoGen para uma fila de tarefas (Celery/Redis) ou WebSockets (FastAPI). O Streamlit apenas consumiria o estado via banco de dados ou socket, evitando bloqueio da UI.
2.  **Persistência:** Salvar históricos de conversas e definições de equipes em um banco de dados (PostgreSQL/MongoDB) para análise posterior.
3.  **Sandboxing Seguro:** Executar o código gerado pelos agentes em contêineres Docker efêmeros e isolados (usando o `DockerCommandLineCodeExecutor` do AutoGen), garantindo que nenhum código malicioso afete o servidor principal.
