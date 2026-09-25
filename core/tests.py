from datetime import datetime, timedelta
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from datetime import date

from .graficos import escala, intervalos_do_grafico, montar_grafico
from .models import InstagramConnection, SeguidoresDia
from .views import (
    _buscar_midias_desde, _buscar_visualizacoes_conta, _motivo_erro_insights, _resolver_periodo, _sincronizar_seguidores,
    _somar_seguidores,
)


def _local(*args):
    return timezone.make_aware(datetime(*args))


def _congelar_em(*args):
    return mock.patch('core.views.timezone.now', return_value=_local(*args))


def _fmt(momento):
    return timezone.localtime(momento).strftime('%d/%m/%Y %H:%M')


class ResolverPeriodoTests(SimpleTestCase):
    def test_hoje_compara_com_ontem_inteiro(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('hoje', None, None)
        self.assertEqual(_fmt(p.desde), '24/09/2026 00:00')
        self.assertEqual(_fmt(p.ate), '24/09/2026 11:25')
        self.assertEqual(_fmt(p.anterior_desde), '23/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '23/09/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. ontem')

    def test_semana_compara_ate_o_mesmo_dia_da_semana_passada(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('semana', None, None)
        self.assertEqual(_fmt(p.desde), '21/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_desde), '14/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '17/09/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. semana passada até qui')

    def test_mes_compara_ate_o_mesmo_dia_do_mes_passado(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.desde), '01/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_desde), '01/08/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '24/08/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. mês passado até 24/08')

    def test_mes_no_dia_31_usa_o_ultimo_dia_do_mes_anterior(self):
        with _congelar_em(2026, 3, 31, 9, 0):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.anterior_ate), '28/02/2026 23:59')

    def test_mes_em_janeiro_compara_com_dezembro_do_ano_anterior(self):
        with _congelar_em(2026, 1, 10, 8, 0):
            p = _resolver_periodo('mes', None, None)
        self.assertEqual(_fmt(p.anterior_desde), '01/12/2025 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '10/12/2025 23:59')

    def test_periodo_desconhecido_usa_este_mes(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('mes_passado', None, None)
        self.assertEqual(p.chave, 'mes')

    def test_periodo_compara_com_os_mesmos_dias_anteriores(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', '2026-09-20', '2026-09-24')
        self.assertEqual(_fmt(p.ate), '24/09/2026 11:25')
        self.assertEqual(_fmt(p.anterior_desde), '15/09/2026 00:00')
        self.assertEqual(_fmt(p.anterior_ate), '19/09/2026 23:59')
        self.assertEqual(p.label_comparacao, 'vs. 5 dias anteriores')

    def test_periodo_com_datas_invertidas_e_corrigido(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', '2026-08-15', '2026-08-01')
        self.assertEqual(p.label, '01/08/2026 – 15/08/2026')

    def test_periodo_invalido_usa_este_mes(self):
        with _congelar_em(2026, 9, 24, 11, 25):
            p = _resolver_periodo('periodo', 'xx', 'yy')
        self.assertEqual(p.chave, 'mes')


def _resposta_erro(status, corpo):
    resp = mock.Mock(status_code=status)
    resp.json.return_value = corpo
    return resp


class MotivoErroInsightsTests(SimpleTestCase):
    def test_post_anterior_a_conta_profissional(self):
        resp = _resposta_erro(400, {'error': {'code': 100, 'error_subcode': 2108006, 'message': 'Media Posted Before Business Account Conversion'}})
        self.assertIn('antes da conta virar profissional', _motivo_erro_insights(resp))

    def test_permissao_nao_concedida(self):
        resp = _resposta_erro(403, {'error': {'code': 10, 'message': 'Application does not have permission for this action'}})
        self.assertIn('permissão de estatísticas', _motivo_erro_insights(resp))

    def test_token_expirado(self):
        resp = _resposta_erro(401, {'error': {'code': 190, 'message': 'Error validating access token'}})
        self.assertIn('expirou', _motivo_erro_insights(resp))

    def test_erro_desconhecido_mostra_mensagem_do_instagram(self):
        resp = _resposta_erro(400, {'error': {'code': 100, 'message': '(#100) The metric views is not supported'}})
        self.assertIn('The metric views is not supported', _motivo_erro_insights(resp))

    def test_resposta_sem_json(self):
        resp = mock.Mock(status_code=502)
        resp.json.side_effect = ValueError
        self.assertIn('HTTP 502', _motivo_erro_insights(resp))


class IntervalosDoGraficoTests(SimpleTestCase):
    hoje = date(2026, 9, 24)

    def test_hoje_mostra_os_ultimos_7_dias(self):
        subtitulo, intervalos = intervalos_do_grafico('hoje', self.hoje, self.hoje, self.hoje)
        self.assertEqual(subtitulo, 'Últimos 7 dias')
        self.assertEqual([i.rotulo for i in intervalos], ['sex 18', 'sáb 19', 'dom 20', 'seg 21', 'ter 22', 'qua 23', 'qui 24'])

    def test_semana_mostra_8_semanas_comecando_na_segunda(self):
        _, intervalos = intervalos_do_grafico('semana', self.hoje, self.hoje, self.hoje)
        self.assertEqual(len(intervalos), 8)
        self.assertEqual((intervalos[0].inicio, intervalos[0].fim), (date(2026, 8, 3), date(2026, 8, 9)))
        self.assertEqual((intervalos[-1].inicio, intervalos[-1].fim), (date(2026, 9, 21), self.hoje))

    def test_mes_mostra_os_meses_do_ano_ate_hoje(self):
        subtitulo, intervalos = intervalos_do_grafico('mes', self.hoje, self.hoje, self.hoje)
        self.assertEqual(subtitulo, 'Meses de 2026')
        self.assertEqual([i.rotulo for i in intervalos], ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set'])
        self.assertEqual(intervalos[1].fim, date(2026, 2, 28))
        self.assertEqual(intervalos[-1].fim, self.hoje)

    def test_periodo_curto_e_por_dia_e_longo_e_por_mes(self):
        subtitulo, intervalos = intervalos_do_grafico('periodo', date(2026, 9, 1), date(2026, 9, 10), self.hoje)
        self.assertEqual((subtitulo, len(intervalos)), ('Por dia', 10))
        subtitulo, intervalos = intervalos_do_grafico('periodo', date(2026, 7, 1), date(2026, 8, 31), self.hoje)
        self.assertEqual((subtitulo, len(intervalos)), ('Por semana', 9))
        subtitulo, intervalos = intervalos_do_grafico('periodo', date(2025, 11, 15), date(2026, 9, 30), self.hoje)
        self.assertEqual(subtitulo, 'Por mês')
        self.assertEqual(intervalos[0].rotulo, 'nov/25')
        self.assertEqual(intervalos[0].inicio, date(2025, 11, 15))
        self.assertEqual(intervalos[-1].fim, self.hoje)


class EscalaEGraficoTests(SimpleTestCase):
    def test_escala_usa_numeros_redondos(self):
        self.assertEqual(escala(0, 37), [0, 10, 20, 30, 40])
        self.assertEqual(escala(0, 2), [0, 1, 2])
        self.assertEqual(escala(-3, 12), [-5, 0, 5, 10, 15])
        self.assertEqual(escala(0, 0), [0, 1])

    def test_barras_negativas_crescem_para_baixo_a_partir_do_zero(self):
        _, intervalos = intervalos_do_grafico('hoje', date(2026, 9, 24), date(2026, 9, 24), date(2026, 9, 24))
        grafico = montar_grafico('x', intervalos, [10, -5, None, 0, 15, 3, 1])
        self.assertEqual(grafico['base'], 25.0)
        positiva, negativa, vazia = grafico['barras'][:3]
        self.assertEqual((positiva['inferior'], positiva['altura']), (25.0, 50.0))
        self.assertEqual((negativa['inferior'], negativa['altura']), (0.0, 25.0))
        self.assertTrue(negativa['negativo'])
        self.assertNotIn('altura', vazia)

    def test_sem_nenhum_dado_fica_vazio(self):
        _, intervalos = intervalos_do_grafico('hoje', date(2026, 9, 24), date(2026, 9, 24), date(2026, 9, 24))
        self.assertTrue(montar_grafico('x', intervalos, [None] * 7)['vazio'])


class SeguidoresTests(TestCase):
    def test_soma_marca_incompleto_quando_falta_dia_encerrado(self):
        por_dia = {date(2026, 9, 21): 3, date(2026, 9, 23): 2}
        self.assertEqual(_somar_seguidores(por_dia, date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 24)), (5, False))
        por_dia[date(2026, 9, 22)] = 1
        self.assertEqual(_somar_seguidores(por_dia, date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 24)), (6, True))
        self.assertEqual(_somar_seguidores({}, date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 24)), (None, False))

    def test_sincronizar_grava_cada_dia_pelo_end_time(self):
        from django.contrib.auth.models import User
        usuario = User.objects.create(username='teste')
        conexao = InstagramConnection.objects.create(user=usuario, instagram_user_id='123', access_token='t')
        resposta = mock.Mock(ok=True)
        resposta.json.return_value = {'data': [{'values': [
            {'value': 4, 'end_time': '2026-09-22T07:00:00+0000'},
            {'value': -1, 'end_time': '2026-09-23T07:00:00+0000'},
        ]}]}
        with mock.patch('core.views.requests.get', return_value=resposta):
            _sincronizar_seguidores(conexao)
            resposta.json.return_value['data'][0]['values'][1]['value'] = 2
            _sincronizar_seguidores(conexao)
        dias = dict(SeguidoresDia.objects.values_list('data', 'novos_seguidores'))
        self.assertEqual(dias, {date(2026, 9, 21): 4, date(2026, 9, 22): 2})


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class DashboardRespostasInesperadasTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.usuario = User.objects.create(username='dono')
        InstagramConnection.objects.create(user=self.usuario, instagram_user_id='999', access_token='t')
        self.client.force_login(self.usuario)

    def _get(self, respostas, params=None):
        def fake_get(url, params=None, timeout=None):
            for sufixo, corpo, ok in respostas:
                if url.endswith(sufixo):
                    resp = mock.Mock(ok=ok, status_code=200 if ok else 400, text='')
                    resp.json.return_value = corpo
                    return resp
            resp = mock.Mock(ok=True, status_code=200, text='')
            resp.json.return_value = {}
            return resp

        with mock.patch('core.views.requests.get', side_effect=fake_get):
            return self.client.get('/dashboard/', params or {})

    def _video(self):
        agora = timezone.now().strftime('%Y-%m-%dT%H:%M:%S+0000')
        return {'id': '1', 'timestamp': agora, 'media_type': 'VIDEO', 'permalink': 'x'}

    def test_dashboard_abre_em_este_mes(self):
        resp = self._get([])
        self.assertEqual(resp.context['periodo_atual'], 'mes')
        self.assertContains(resp, '<option value="mes" selected>')

    def test_fotos_e_carrosseis_tambem_mostram_visualizacoes(self):
        agora = timezone.now().strftime('%Y-%m-%dT%H:%M:%S+0000')
        posts = [
            {'id': '7', 'timestamp': agora, 'media_type': 'IMAGE', 'permalink': 'x', 'media_url': 'https://x/7.jpg'},
            {'id': '8', 'timestamp': agora, 'media_type': 'CAROUSEL_ALBUM', 'permalink': 'x', 'media_url': 'https://x/8.jpg'},
        ]
        resp = self._get([
            ('/media', {'data': posts}, True),
            ('/7/insights', {'data': [{'name': 'views', 'values': [{'value': 4321}]}]}, True),
            ('/8/insights', {'data': [{'name': 'views', 'total_value': {'value': 987}}]}, True),
        ])
        self.assertContains(resp, '4.321 visualizações')
        self.assertContains(resp, '4,3 mil')
        self.assertContains(resp, '987 visualizações')

    def _posts(self, quantidade):
        agora = timezone.now()
        return [{
            'id': str(i), 'media_type': 'IMAGE', 'permalink': 'x', 'media_url': f'https://x/{i}.jpg',
            'timestamp': (agora - timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M:%S+0000'),
            'like_count': (i * 37) % 101,
        } for i in range(quantidade)]

    def _ids_exibidos(self, resp):
        return [m['id'] for m in resp.context['midias']]

    def test_ranking_padrao_e_mais_recentes(self):
        resp = self._get([('/media', {'data': self._posts(60)}, True)])
        self.assertEqual(resp.context['ordem_atual'], 'recentes')
        self.assertEqual(self._ids_exibidos(resp), [str(i) for i in range(12)])

    def test_ranking_por_curtidas_considera_as_ultimas_50(self):
        posts = self._posts(60)
        with mock.patch('core.views.requests.get') as get:
            def responder(url, params=None, timeout=None):
                resp = mock.Mock(ok=True, status_code=200, text='')
                resp.json.return_value = {'data': posts} if url.endswith('/media') else {}
                return resp
            get.side_effect = responder
            resp = self.client.get('/dashboard/', {'ordem': 'curtidas'})
        esperado = sorted(posts[:50], key=lambda m: m['like_count'], reverse=True)[:12]
        self.assertEqual(self._ids_exibidos(resp), [m['id'] for m in esperado])
        self.assertContains(resp, 'Entre as últimas 50 publicações')

    def test_ranking_por_visualizacoes_deixa_sem_dado_por_ultimo(self):
        posts = self._posts(4)
        views = {'0': 10, '1': None, '2': 900, '3': 55}

        def responder(url, params=None, timeout=None):
            resp = mock.Mock(ok=True, status_code=200, text='')
            if url.endswith('/media'):
                resp.json.return_value = {'data': posts}
            elif url.endswith('/insights') and url.rsplit('/', 2)[-2] in views:
                valor = views[url.rsplit('/', 2)[-2]]
                if valor is None:
                    resp.ok, resp.status_code = False, 400
                    resp.json.return_value = {'error': {'code': 100, 'error_subcode': 2108006}}
                else:
                    resp.json.return_value = {'data': [{'name': 'views', 'values': [{'value': valor}]}]}
            else:
                resp.json.return_value = {}
            return resp

        with mock.patch('core.views.requests.get', side_effect=responder):
            resp = self.client.get('/dashboard/', {'ordem': 'visualizacoes'})
        self.assertEqual(self._ids_exibidos(resp), ['2', '3', '0', '1'])

    def test_ordem_invalida_volta_para_recentes(self):
        resp = self._get([], {'ordem': 'xyz'})
        self.assertEqual(resp.context['ordem_atual'], 'recentes')

    def test_post_sem_media_url_nao_derruba_a_pagina(self):
        resp = self._get([('/media', {'data': [self._video()]}, True)])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'class="media-card"')

    def test_visualizacoes_com_total_value_nulo(self):
        resp = self._get([
            ('/media', {'data': [self._video()]}, True),
            ('/1/insights', {'data': [{'name': 'views', 'total_value': None}]}, True),
        ])
        self.assertEqual(resp.status_code, 200)

    def test_erro_de_visualizacoes_com_mensagem_nula(self):
        resp = self._get([
            ('/media', {'data': [self._video()]}, True),
            ('/1/insights', {'error': {'code': 100, 'message': None}}, False),
        ])
        self.assertEqual(resp.status_code, 200)

    def test_erro_inesperado_mostra_aviso_em_vez_de_500(self):
        with mock.patch('core.views._somar_engajamento', side_effect=RuntimeError('boom')), \
                self.assertLogs('core.views', level='ERROR'):
            resp = self._get([])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Não foi possível carregar os dados do Instagram')

    def test_token_longo_e_aceito(self):
        conexao = InstagramConnection.objects.get(user=self.usuario)
        conexao.access_token = 'I' * 400
        conexao.save()
        conexao.refresh_from_db()
        self.assertEqual(len(conexao.access_token), 400)


class VisualizacoesContaTests(SimpleTestCase):
    conexao = InstagramConnection(instagram_user_id='123', access_token='t')

    def _resposta(self, valor):
        resp = mock.Mock(ok=True)
        resp.json.return_value = {'data': [{'name': 'views', 'total_value': {'value': valor}}]}
        return resp

    def test_periodo_longo_e_somado_em_partes_de_30_dias(self):
        with mock.patch('core.views.requests.get', side_effect=[self._resposta(100), self._resposta(40)]) as get:
            total = _buscar_visualizacoes_conta(self.conexao, _local(2026, 7, 1), _local(2026, 8, 15))
        self.assertEqual(total, 140)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs['params']['metric_type'], 'total_value')
        primeira, segunda = (c.kwargs['params'] for c in get.call_args_list)
        self.assertEqual(primeira['until'], segunda['since'])
        self.assertLessEqual(primeira['until'] - primeira['since'], 30 * 86400)

    def test_recusa_do_instagram_vira_sem_dados(self):
        recusa = mock.Mock(ok=False, status_code=400, text='{"error": {}}')
        with mock.patch('core.views.requests.get', return_value=recusa):
            self.assertIsNone(_buscar_visualizacoes_conta(self.conexao, _local(2026, 9, 1), _local(2026, 9, 24)))


class NumeroCompactoTests(SimpleTestCase):
    def test_formato_estilo_instagram(self):
        from .templatetags.nexora import compacto
        casos = {0: '0', 999: '999', 1000: '1 mil', 1523: '1,5 mil', 12345: '12 mil',
                 999950: '1 mi', 1250000: '1,2 mi', -2300: '-2,3 mil', None: None}
        for valor, esperado in casos.items():
            self.assertEqual(compacto(valor), esperado, valor)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class AgendaTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.usuario = User.objects.create(username='agenda')
        self.outro = User.objects.create(username='outro')
        self.client.force_login(self.usuario)

    def test_calendario_de_setembro_de_2026_comeca_no_domingo_30_de_agosto(self):
        resp = self.client.get('/programacao/', {'mes': '2026-09', 'dia': '2026-09-24'})
        self.assertEqual(resp.status_code, 200)
        semanas = resp.context['semanas']
        self.assertEqual(semanas[0][0]['data'], date(2026, 8, 30))
        self.assertTrue(semanas[0][0]['fora_do_mes'])
        self.assertEqual(semanas[0][2]['data'], date(2026, 9, 1))
        self.assertEqual(resp.context['titulo_mes'], 'Setembro 2026')
        self.assertEqual(resp.context['titulo_selecionado'], 'Quinta, 24 de setembro')
        self.assertEqual((resp.context['mes_anterior'], resp.context['mes_seguinte']), ('2026-08', '2026-10'))

    def test_virada_de_ano_na_navegacao(self):
        resp = self.client.get('/programacao/', {'mes': '2026-12'})
        self.assertEqual(resp.context['mes_seguinte'], '2027-01')
        resp = self.client.get('/programacao/', {'mes': '2026-01'})
        self.assertEqual(resp.context['mes_anterior'], '2025-12')

    def test_adicionar_concluir_e_excluir_item(self):
        from .models import ItemAgenda
        resp = self.client.post('/programacao/itens/', {'data': '2026-09-24', 'titulo': 'Gravar reels', 'horario': '14:30'})
        self.assertRedirects(resp, '/programacao/?mes=2026-09&dia=2026-09-24', fetch_redirect_response=False)
        item = ItemAgenda.objects.get(usuario=self.usuario)
        self.assertEqual(str(item.horario), '14:30:00')

        pagina = self.client.get('/programacao/', {'mes': '2026-09', 'dia': '2026-09-24'})
        self.assertContains(pagina, 'Gravar reels')

        self.client.post(f'/programacao/itens/{item.id}/concluir/')
        item.refresh_from_db()
        self.assertTrue(item.concluido)

        self.client.post(f'/programacao/itens/{item.id}/excluir/')
        self.assertFalse(ItemAgenda.objects.exists())

    def test_item_sem_titulo_ou_data_invalida_nao_e_criado(self):
        from .models import ItemAgenda
        self.client.post('/programacao/itens/', {'data': '2026-09-24', 'titulo': '   '})
        self.client.post('/programacao/itens/', {'data': 'ontem', 'titulo': 'x'})
        self.assertFalse(ItemAgenda.objects.exists())

    def test_nao_mexe_em_item_de_outro_usuario(self):
        from .models import ItemAgenda
        item = ItemAgenda.objects.create(usuario=self.outro, data=date(2026, 9, 24), titulo='Privado')
        self.assertEqual(self.client.post(f'/programacao/itens/{item.id}/concluir/').status_code, 404)
        self.assertEqual(self.client.post(f'/programacao/itens/{item.id}/excluir/').status_code, 404)
        self.assertNotContains(self.client.get('/programacao/', {'mes': '2026-09', 'dia': '2026-09-24'}), 'Privado')


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class QuadroTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.usuario = User.objects.create(username='quadro')
        self.outro = User.objects.create(username='outro')
        self.client.force_login(self.usuario)

    def _listas(self):
        from .models import ListaTarefas
        return list(ListaTarefas.objects.filter(usuario=self.usuario))

    def _titulos(self, lista):
        return list(lista.cartoes.values_list('titulo', flat=True))

    def test_primeiro_acesso_cria_colunas_padrao(self):
        resp = self.client.get('/tarefas/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([l.titulo for l in self._listas()], ['A fazer', 'Fazendo', 'Feito'])
        self.client.get('/tarefas/')
        self.assertEqual(len(self._listas()), 3)

    def test_criar_e_mover_cartoes_mantendo_a_ordem(self):
        self.client.get('/tarefas/')
        a_fazer, fazendo, _ = self._listas()
        for titulo in ['Um', 'Dois', 'Tres']:
            resp = self.client.post(f'/tarefas/listas/{a_fazer.id}/cartoes/', {'titulo': titulo})
        self.assertRedirects(resp, f'/tarefas/#lista-{a_fazer.id}', fetch_redirect_response=False)
        self.assertEqual(self._titulos(a_fazer), ['Um', 'Dois', 'Tres'])

        tres = a_fazer.cartoes.get(titulo='Tres')
        resp = self.client.post(f'/tarefas/cartoes/{tres.id}/mover/', {'lista': a_fazer.id, 'posicao': 0},
                                HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(resp.json(), {'ok': True})
        self.assertEqual(self._titulos(a_fazer), ['Tres', 'Um', 'Dois'])

        um = a_fazer.cartoes.get(titulo='Um')
        self.client.post(f'/tarefas/cartoes/{um.id}/mover/', {'lista': fazendo.id})
        self.assertEqual(self._titulos(a_fazer), ['Tres', 'Dois'])
        self.assertEqual(self._titulos(fazendo), ['Um'])

    def test_criar_renomear_e_excluir_coluna(self):
        from .models import Cartao
        self.client.get('/tarefas/')
        self.client.post('/tarefas/listas/', {'titulo': 'Ideias'})
        ideias = self._listas()[-1]
        self.assertEqual(ideias.titulo, 'Ideias')
        self.client.post(f'/tarefas/listas/{ideias.id}/renomear/', {'titulo': 'Ideias de post'})
        ideias.refresh_from_db()
        self.assertEqual(ideias.titulo, 'Ideias de post')
        self.client.post(f'/tarefas/listas/{ideias.id}/cartoes/', {'titulo': 'Carrossel'})
        self.client.post(f'/tarefas/listas/{ideias.id}/excluir/')
        self.assertEqual(len(self._listas()), 3)
        self.assertFalse(Cartao.objects.filter(titulo='Carrossel').exists())

    def test_nao_mexe_no_quadro_de_outro_usuario(self):
        from .models import Cartao, ListaTarefas
        self.client.get('/tarefas/')
        minha = self._listas()[0]
        alheia = ListaTarefas.objects.create(usuario=self.outro, titulo='Deles')
        cartao_alheio = Cartao.objects.create(lista=alheia, titulo='Segredo')
        meu_cartao = Cartao.objects.create(lista=minha, titulo='Meu')

        self.assertEqual(self.client.post(f'/tarefas/listas/{alheia.id}/cartoes/', {'titulo': 'x'}).status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/listas/{alheia.id}/excluir/').status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/cartoes/{cartao_alheio.id}/excluir/').status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/cartoes/{cartao_alheio.id}/mover/', {'lista': minha.id}).status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/cartoes/{meu_cartao.id}/mover/', {'lista': alheia.id}).status_code, 404)
        self.assertEqual(self.client.post(f'/tarefas/cartoes/{meu_cartao.id}/mover/', {'lista': 'abc'}).status_code, 404)
        self.assertNotContains(self.client.get('/tarefas/'), 'Segredo')


class PaginacaoMidiasTests(SimpleTestCase):
    conexao = InstagramConnection(instagram_user_id='123', access_token='t')

    def test_busca_paginas_ate_ter_o_minimo_mesmo_com_periodo_curto(self):
        agora = timezone.now()

        def pagina(inicio, proxima):
            dados = [{'id': str(i), 'timestamp': (agora - timedelta(days=i)).strftime('%Y-%m-%dT%H:%M:%S+0000')}
                     for i in range(inicio, inicio + 25)]
            resp = mock.Mock(ok=True)
            resp.raise_for_status = lambda: None
            resp.json.return_value = {'data': dados, 'paging': {'next': proxima} if proxima else {}}
            return resp

        respostas = [pagina(0, 'p2'), pagina(25, 'p3'), pagina(50, 'p4')]
        with mock.patch('core.views.requests.get', side_effect=respostas) as get:
            midias, cobertas_desde = _buscar_midias_desde(self.conexao, agora - timedelta(days=2), minimo=50)
        self.assertEqual(len(midias), 50)
        self.assertEqual(get.call_count, 2)
        self.assertIsNone(cobertas_desde)


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class PublicoTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.usuario = User.objects.create(username='publico')
        self.client.force_login(self.usuario)

    def _conectar(self):
        InstagramConnection.objects.create(user=self.usuario, instagram_user_id='999', access_token='t')

    def _demografia(self, pares):
        return {'data': [{'name': 'follower_demographics', 'total_value': {'breakdowns': [{
            'dimension_keys': ['x'],
            'results': [{'dimension_values': [chave], 'value': valor} for chave, valor in pares],
        }]}}]}

    def _get(self, respostas_por_metrica):
        def responder(url, params=None, timeout=None):
            resp = mock.Mock(ok=True, status_code=200, text='')
            params = params or {}
            if url.endswith('/me'):
                resp.json.return_value = {'followers_count': 1000, 'profile_picture_url': ''}
                return resp
            chave = params.get('breakdown') or params.get('metric')
            ok, corpo = respostas_por_metrica.get(chave, (True, {}))
            resp.ok, resp.status_code = ok, 200 if ok else 400
            resp.json.return_value = corpo
            return resp

        with mock.patch('core.publico.requests.get', side_effect=responder), \
                mock.patch('core.views.requests.get', side_effect=responder):
            return self.client.get('/publico/')

    def test_sem_conta_mostra_botao_de_conectar(self):
        resp = self.client.get('/publico/')
        self.assertContains(resp, 'Conectar com Instagram')

    def test_mostra_publico_com_porcentagens(self):
        self._conectar()
        horas = {str(h): (50 if h == 16 else 10) for h in range(24)}
        resp = self._get({
            'city': (True, self._demografia([('São Paulo, São Paulo', 300), ('Rio de Janeiro, Rio de Janeiro', 120)])),
            'country': (True, self._demografia([('BR', 900), ('PT', 60), ('ZZ', 5)])),
            'age': (True, self._demografia([('25-34', 500), ('18-24', 300), ('35-44', 200)])),
            'gender': (True, self._demografia([('F', 600), ('M', 380), ('U', 20)])),
            'online_followers': (True, {'data': [{'values': [{'value': horas}, {'value': horas}]}]}),
        })
        self.assertEqual(resp.status_code, 200)
        cidades = resp.context['cidades']['dados']
        self.assertEqual(cidades[0]['nome'], 'São Paulo, São Paulo')
        self.assertAlmostEqual(cidades[0]['percentual'], 30.0)
        paises = [p['nome'] for p in resp.context['paises']['dados']]
        self.assertEqual(paises, ['Brasil', 'Portugal', 'ZZ'])
        self.assertEqual([i['nome'] for i in resp.context['idades']['dados']][:3], ['13-17', '18-24', '25-34'])
        self.assertAlmostEqual(resp.context['idades']['dados'][2]['percentual'], 50.0)
        self.assertEqual([g['nome'] for g in resp.context['generos']['dados']], ['Feminino', 'Masculino', 'Não informado'])
        self.assertContains(resp, '30,0%')
        self.assertContains(resp, '60,0%')
        self.assertContains(resp, 'id="loc-cidades"')
        self.assertContains(resp, 'id="loc-paises" hidden')
        self.assertNotContains(resp, 'Principais cidades')
        horarios = resp.context['horarios']['dados']
        self.assertEqual(len(horarios['barras']), 24)
        self.assertIn('Pico às', horarios['subtitulo'])

    def test_conta_pequena_mostra_motivo_em_cada_bloco(self):
        self._conectar()
        recusa = (False, {'error': {'code': 100, 'message': 'Not enough users. Requires at least 100 followers'}})
        resp = self._get({'city': recusa, 'country': recusa, 'age': recusa, 'gender': recusa, 'online_followers': recusa})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'pelo menos 100 seguidores', count=5)


class HorariosAtivosTests(SimpleTestCase):
    def test_converte_horario_do_pacifico_para_brasilia(self):
        from .publico import _medias_por_hora_local
        # 24/09/2026: Pacífico em horário de verão (UTC-7), Brasília UTC-3 → 4 horas de diferença.
        referencia = _local(2026, 9, 24, 12, 0)
        medias = _medias_por_hora_local([{'0': 10, '20': 40}, {'0': 20, '20': 60}], referencia)
        self.assertEqual(medias[4], 15)
        self.assertEqual(medias[0], 50)
        self.assertEqual(medias[1], 0)

    def test_no_inverno_do_hemisferio_norte_a_diferenca_e_5_horas(self):
        from .publico import _medias_por_hora_local
        referencia = _local(2026, 1, 15, 12, 0)
        self.assertEqual(_medias_por_hora_local([{'0': 7}], referencia)[5], 7)
